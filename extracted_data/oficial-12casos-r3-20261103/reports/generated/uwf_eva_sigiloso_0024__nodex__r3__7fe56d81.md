## Diagnóstico

Se identifica un patrón altamente anómalo con 264 solicitudes DNS fallidas (conexiones en estado S0 sin respuesta) originadas desde el host 143.88.255.10 hacia el servidor DNS interno 10.0.10.1 en una ventana de 30 minutos. Este comportamiento es consistente con intentos de tunelización DNS o canal encubierto para comando y control bajo la técnica T1071.004, o bien el uso de algoritmos de generación de dominios (DGA, T1568.002) que generan consultas a dominios inexistentes o no enrutables. Se recomienda aislar preventivamente la IP 143.88.255.10, inspeccionar el payload de las consultas DNS para verificar cadenas aleatorias/subdominios de exfiltración y auditar procesos activos en el equipo de origen.

## Evaluación del auditor

Se observa un comportamiento anómalo consistente en ráfagas periódicas de consultas DNS UDP (puerto 53) cada aproximadamente 30 segundos desde el host 143.88.255.10 hacia la IP 10.0.10.1, todas quedando en estado S0 (sin respuesta). Sin embargo, el diagnóstico propuesto de tunelización DNS (T1071.004) o DGA (T1568.002) no está respaldado: no se dispone del registro de nombres de dominio consultados ni de respuestas del servidor, y la cadencia estricta de reintentos cada 30 segundos hacia una IP no responsiva es característica de una falla operativa de red, servidor DNS caído o error de configuración de resolución de nombres, no de una intrusión o canal encubierto activo.

## Comandos de mitigación propuestos

- iptables -I INPUT 1 -s 143.88.255.10 -j LOG --log-prefix "[ALERTA-DNS-BLOCKED]: " --log-level 4
- iptables -I INPUT 2 -s 143.88.255.10 -j DROP
- iptables -I FORWARD 1 -s 143.88.255.10 -j DROP
- ufw insert 1 deny from 143.88.255.10 to any
- conntrack -D -s 143.88.255.10
- tcpdump -nn -i any -s 0 -c 500 host 143.88.255.10 and port 53 -w /var/log/dns_exfiltration_evidence.pcap &