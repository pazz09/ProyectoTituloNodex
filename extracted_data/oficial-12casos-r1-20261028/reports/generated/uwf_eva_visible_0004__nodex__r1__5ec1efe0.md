## Diagnóstico

Se ha detectado un volumen anómalo y repetitivo de tráfico DNS (238 eventos, de los cuales 279 del total del lote fueron catalogados como críticos) concentrado principalmente desde la dirección IP 143.88.255.10 hacia el servidor DNS interno 10.0.10.1:53/udp con 213 peticiones fallidas o sin respuesta (estado de conexión Zeek S0). Este comportamiento sugiere un intento de comunicación anómala mediante el protocolo DNS, posiblemente vinculado a técnicas de canal encubierto, tunelización o balizamiento C2 descritas en T1071.004, o bien un ataque de denegación de servicio/escaneo hacia la infraestructura de resolución. Adicionalmente, se identificó actividad anómala entre 143.88.18.12 y 143.88.18.11 con 60 intentos fallidos. Se recomienda aislar o restringir temporalmente el tráfico saliente/DNS desde el host 143.88.255.10, inspeccionar las consultas DNS específicas enviadas para descartar dominios maliciosos o exfiltración, y auditar el host 143.88.18.12.

## Evaluación del auditor

El diagnóstico es acertado al identificar dos anomalías críticas en el tráfico de red: un balizamiento o comunicación DNS repetitiva no respondida (estado S0) con cadencia fija de aproximadamente 30 segundos desde 143.88.255.10 hacia 10.0.10.1, y un escaneo evidente de puertos TCP (estado SH) dirigido por 143.88.18.12 contra 143.88.18.11 abarcando múltiples servicios críticos (SSH, RDP, Telnet, SMB, VNC, etc.). Las medidas de contención mediante iptables y la recolección de pcap son apropiadas y pertinentes.

## Comandos de mitigación propuestos

- iptables -I INPUT -s 143.88.255.10 -p udp --dport 53 -j DROP
- iptables -I INPUT -s 143.88.255.10 -p tcp --dport 53 -j DROP
- iptables -I FORWARD -s 143.88.255.10 -d 10.0.10.1 -p udp --dport 53 -j DROP
- iptables -I FORWARD -s 143.88.255.10 -d 10.0.10.1 -p tcp --dport 53 -j DROP
- iptables -I FORWARD -s 143.88.18.12 -d 143.88.18.11 -j DROP
- conntrack -D -s 143.88.255.10
- tcpdump -nn -i any host 143.88.255.10 and port 53 -w /var/log/dns_investigation_143.88.255.10.pcap -c 200 &