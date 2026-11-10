## Diagnóstico

Se detectó un escaneo de puertos TCP activo desde 143.88.18.12 hacia 143.88.18.11 barriendo múltiples puertos de administración y servicios (SSH, Telnet, SMB, RDP, VNC, HTTP), complementado con ráfagas continuas de consultas DNS no respondidas (estado S0) desde 143.88.255.10 hacia 10.0.10.1.

## Evaluación del auditor

La actividad de 143.88.18.12 corresponde a reconocimiento de red (escaneo de puertos SYN/half-open en ráfaga rápida contra un host interno). Paralelamente, 143.88.255.10 genera tráfico DNS anómalo no respondido hacia un servidor interno, lo que indica un intento fallido de resolución masiva o falla de enrutamiento/disponibilidad.

## Comandos de mitigación propuestos

- iptables -A INPUT -s 143.88.18.12 -j DROP
- iptables -A FORWARD -s 143.88.18.12 -j DROP