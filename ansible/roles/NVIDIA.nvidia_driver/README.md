# NVIDIA.nvidia_driver (stub)

This shadows the Ansible Galaxy role of the same name, which `grycap.docker`
pulls in as a hard dependency and which would otherwise install a public NVIDIA
driver over our vGPU guest driver and reboot the node.

It verifies instead of installing. The reasoning is in `tasks/main.yml`.

Shadowing works because `ansible/ansible.cfg` lists `roles` before
`~/.ansible/roles` in `roles_path`; the first match wins.

Delete this directory to get upstream's behaviour back — but read what it does
first.
