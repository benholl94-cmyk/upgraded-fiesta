//! `hm_sdk::tls` — gemeinsamer HTTPS-Client fuer alle Channel-Crates und
//! `hm-tool-web`. Aktiviert durch das Cargo-Feature `tls`. Ohne dieses
//! Feature liefert jede oeffentliche Funktion einen klaren Fehler, der zum
//! Aktivieren der Features rat (statt lautlos HTTP-auf-HTTPS zu mischen).
//!
//! ## Design
//!
//! - Hand-rolled HTTP/1.1 ueber `rustls::Stream<ClientConnection, TcpStream>`.
//!   Kein zusatzlicher HTTP-Client-Crate -- passt zum Stil der uebrigen
//!   Crates (`hm-storage::RemoteHttpStorage` arbeitet genauso roh).
//! - Mozilla-CA-Bundles via `webpki_roots::TLS_SERVER_ROOTS` -- keine
//!   System-Store-Abhaengigkeit, wichtig fuer minimale Container.
//! - Antwort: rohe Bytes (Status-Line + Header + Body). Caller parsen
//!   selbst -- so bleibt die Crate agnostisch gegen Telegram/Discord/Slack
//!   unterschiedliche JSON-Formen.
//!
//! ## Warum getrennt von `hm-sdk`-Default
//!
//! `rustls` ist eine schwere Abhaengigkeit (~1 MB kompiliert, +25 s Build).
//! Wer den Channel nur eingehend (Webhook) betreibt, braucht den ganzen
//! TLS-Stack nicht. Deshalb opt-in.

#[cfg(feature = "tls")]
mod imp {
    use std::sync::Arc;

    use rustls::pki_types::ServerName;
    use rustls::{ClientConfig, ClientConnection, RootCertStore, Stream};
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::TcpStream;

    /// Baut einen `ClientConfig` mit den Mozilla-Standard-Roots. Das ist
    /// absichtlich jedes Mal eine neue Config -- der Channel-Crate
    /// allokiert nur beim Aufruf, nicht pro Frame.
    fn client_config() -> anyhow::Result<Arc<ClientConfig>> {
        let mut roots = RootCertStore::empty();
        roots.extend(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());
        let config = ClientConfig::builder()
            .with_root_certificates(roots)
            .with_no_client_auth();
        Ok(Arc::new(config))
    }

    /// Parst eine URL der Form `https://host[:port]/pfad?query` in
    /// `(host, port, path_and_query)`. Port faellt auf 443 zurueck wenn
    /// weggelassen. Pfad faellt auf `/` zurueck wenn leer.
    fn split_https_url(url: &str) -> anyhow::Result<(String, u16, String)> {
        let rest = url
            .strip_prefix("https://")
            .ok_or_else(|| anyhow::anyhow!("only https:// URLs are supported, got: {url}"))?;
        let (authority, path) = match rest.find('/') {
            Some(pos) => (&rest[..pos], &rest[pos..]),
            None => (rest, "/"),
        };
        let (host, port) = match authority.rfind(':') {
            Some(pos) => {
                let p: u16 = authority[pos + 1..]
                    .parse()
                    .map_err(|_| anyhow::anyhow!("invalid port in URL: {url}"))?;
                (&authority[..pos], p)
            }
            None => (authority, 443),
        };
        if host.is_empty() {
            anyhow::bail!("empty host in URL: {url}");
        }
        Ok((host.to_string(), port, path.to_string()))
    }

    /// POSTet `body` an `url` mit den gegebenen Headern, liest die gesamte
    /// Antwort und liefert sie als rohe Bytes. Blockiert den aktuellen Thread
    /// fuer DNS+TCP+TLS+HTTP, ist also `async`-freundlich.
    pub async fn post(url: &str, headers: &[(&str, &str)], body: &[u8]) -> anyhow::Result<Vec<u8>> {
        let (host, port, path) = split_https_url(url)?;
        let server_name = ServerName::try_from(host.clone())
            .map_err(|e| anyhow::anyhow!("invalid server name {host}: {e}"))?;

        let config = client_config()?;
        let conn = ClientConnection::new(config, server_name)?;
        let tcp = TcpStream::connect((host.as_str(), port)).await?;
        let mut tls = Stream::new(conn, tcp);

        // Anfragezeile + Header aufbauen. Host-Header ist bei HTTP/1.1
        // Pflicht; Connection: close spart den Tear-Down-Handshake.
        let mut request = format!(
            "POST {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\nContent-Length: {}\r\n",
            body.len()
        );
        for (k, v) in headers {
            request.push_str(&format!("{k}: {v}\r\n"));
        }
        request.push_str("\r\n");

        tls.write_all(request.as_bytes()).await?;
        tls.write_all(body).await?;

        let mut response = Vec::new();
        tls.read_to_end(&mut response).await?;
        Ok(response)
    }

    /// Wie `post`, aber `GET`. Wird von `hm-tool-web` benutzt.
    pub async fn get(url: &str, headers: &[(&str, &str)]) -> anyhow::Result<Vec<u8>> {
        let (host, port, path) = split_https_url(url)?;
        let server_name = ServerName::try_from(host.clone())
            .map_err(|e| anyhow::anyhow!("invalid server name {host}: {e}"))?;

        let config = client_config()?;
        let conn = ClientConnection::new(config, server_name)?;
        let tcp = TcpStream::connect((host.as_str(), port)).await?;
        let mut tls = Stream::new(conn, tcp);

        let mut request = format!(
            "GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n"
        );
        for (k, v) in headers {
            request.push_str(&format!("{k}: {v}\r\n"));
        }
        request.push_str("\r\n");

        tls.write_all(request.as_bytes()).await?;

        let mut response = Vec::new();
        tls.read_to_end(&mut response).await?;
        Ok(response)
    }
}

/// Stub, aktiv wenn das Feature `tls` aus ist. Liefert einen klaren,
/// maschinenlesbaren Fehler, der die User zum Aktivieren der Features
/// fuehrt. Niemand soll stillschweigend HTTP statt HTTPS senden.
#[cfg(not(feature = "tls"))]
mod imp {
    pub async fn post(_url: &str, _headers: &[(&str, &str)], _body: &[u8]) -> anyhow::Result<Vec<u8>> {
        anyhow::bail!(
            "hm-sdk::tls::post requires the 'tls' feature. \
             Build the calling crate with --features tls (e.g. \
             `cargo build -p hm-channel-telegram --features tls`). \
             Without TLS, this crate refuses to send anything to HTTPS endpoints."
        )
    }

    pub async fn get(_url: &str, _headers: &[(&str, &str)]) -> anyhow::Result<Vec<u8>> {
        anyhow::bail!(
            "hm-sdk::tls::get requires the 'tls' feature. \
             Build the calling crate with --features tls (e.g. \
             `cargo build -p hm-tool-web --features tls`)."
        )
    }
}

pub use imp::{get, post};

#[cfg(test)]
mod tests {
    use super::*;

    /// Wenn das `tls`-Feature aus ist, muss `post` einen klaren, gut
    /// maschinenlesbaren Fehler liefern -- nicht etwa `unimplemented!()`
    /// oder gar nichts.
    #[cfg(not(feature = "tls"))]
    #[tokio::test]
    async fn post_without_tls_feature_returns_helpful_error() {
        let err = post("https://example.com/foo", &[], b"{}").await.unwrap_err();
        let msg = err.to_string();
        assert!(
            msg.contains("requires the 'tls' feature"),
            "error must mention the feature, got: {msg}"
        );
        assert!(
            msg.contains("--features tls"),
            "error must show the build command, got: {msg}"
        );
    }

    #[cfg(not(feature = "tls"))]
    #[tokio::test]
    async fn get_without_tls_feature_returns_helpful_error() {
        let err = get("https://example.com/foo", &[]).await.unwrap_err();
        assert!(err.to_string().contains("requires the 'tls' feature"));
    }

    /// URL-Parsing wird nur im `tls`-Fall getestet, weil `split_https_url`
    /// privat ist und im Stub-Modul nicht existiert.
    #[cfg(feature = "tls")]
    #[test]
    fn split_https_url_parses_minimal() {
        let (host, port, path) = split_https_url("https://example.com/foo?x=1").unwrap();
        assert_eq!(host, "example.com");
        assert_eq!(port, 443);
        assert_eq!(path, "/foo?x=1");
    }

    #[cfg(feature = "tls")]
    #[test]
    fn split_https_url_with_explicit_port() {
        let (host, port, path) = split_https_url("https://api.example.com:8443/v1/messages").unwrap();
        assert_eq!(host, "api.example.com");
        assert_eq!(port, 8443);
        assert_eq!(path, "/v1/messages");
    }

    #[cfg(feature = "tls")]
    #[test]
    fn split_https_url_no_path_defaults_to_slash() {
        let (host, port, path) = split_https_url("https://example.com").unwrap();
        assert_eq!(host, "example.com");
        assert_eq!(port, 443);
        assert_eq!(path, "/");
    }

    #[cfg(feature = "tls")]
    #[test]
    fn split_https_url_rejects_http() {
        assert!(split_https_url("http://example.com/foo").is_err());
    }

    #[cfg(feature = "tls")]
    #[test]
    fn split_https_url_rejects_empty_host() {
        assert!(split_https_url("https:///foo").is_err());
    }
}
