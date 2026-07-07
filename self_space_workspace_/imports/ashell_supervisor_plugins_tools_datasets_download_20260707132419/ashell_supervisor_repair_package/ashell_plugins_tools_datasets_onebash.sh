# pbpaste > ashell_plugins_tools_datasets_onebash.sh
# sh ashell_plugins_tools_datasets_onebash.sh

set -u

mkdir -p local_usr/sys/bin
mkdir -p local_usr/sys/plugins/env_probe
mkdir -p local_usr/sys/plugins/file_inventory
mkdir -p local_usr/sys/etc/channels
mkdir -p local_usr/sys/etc/datasets
mkdir -p local_usr/sys/var/lib/data
mkdir -p local_usr/sys/var/run
mkdir -p local_usr/sys/var/log

python3 local_usr/sys/bin/plugin_registry.py validate
python3 local_usr/sys/bin/dataset_operator.py validate
python3 local_usr/sys/bin/plugin_runner.py env_probe
python3 local_usr/sys/bin/plugin_runner.py file_inventory
