# a-Shell Full Environment Runtime

Commands:

```sh
python3 scripts/mobile_operator.py status
python3 scripts/mobile_operator.py validate
python3 local_usr/sys/bin/ashell_supervisor.py health
python3 local_usr/sys/bin/ashell_supervisor.py repair
python3 local_usr/sys/bin/ashell_supervisor.py export
python3 local_usr/sys/bin/ashell_supervisor.py serve
```

Local supervisor routes:

```text
http://127.0.0.1:8097/health
http://127.0.0.1:8097/state
http://127.0.0.1:8097/repair
```
