## Diagnóstico

Se observa un patrón persistente y anómalo de 261 consultas DNS originadas desde 143.88.255.10 hacia la IP privada 10.0.10.1, registrando un 100% de intentos fallidos/sin respuesta exitosa en una ventana de ~31 minutos. Este comportamiento es característico de una desconfiguración operativa (resolutor DNS inalcanzable, fuera de servicio o error de enrutamiento interno) o un servicio/demonio en bucle de reintento. Aunque el riesgo inmediato de compromiso es bajo debido a la falta de comunicación bidireccional, no se descarta completamente un intento de tunelización o balizamiento fallido. Acciones recomendadas: 1) Inspección de capa de aplicación (L7) mediante captura de paquetes (PCAP) o registro Zeek dns.log para analizar los nombres de dominio consultados (QNAME), tipos de registro (RRType) y longitud de payload, descartando técnicas de tunneling (T1071.004) o DGA; 2) Verificación de alcanzabilidad de 10.0.10.1 a nivel de red y validación de la configuración de resolutores DNS en el host 143.88.255.10; 3) Mitigación progresiva no disruptiva mediante rate-limiting temporal en el firewall perimetral/interno para el tráfico UDP/TCP 53 hacia dicho destino y reasignación del servidor DNS primario/secundario en el host afectado.

## Evaluación del auditor

El diagnóstico es acertado. Se observa un patrón repetitivo de intentos de conexión DNS (UDP/53) desde 143.88.255.10 hacia la IP privada 10.0.10.1 que finalizan sistemáticamente en estado S0 (sin respuesta). Este comportamiento corresponde típicamente a un resolutor local inalcanzable o un servicio en bucle de reintento tras fallos de conectividad. No hay indicios ni evidencia de tráfico malicioso bidireccional, compromiso del host ni exfiltración en los registros observados, catalogándose adecuadamente como una anomalía operativa de red.

## Comandos de mitigación propuestos

- tcpdump -ni any host 143.88.255.10 and host 10.0.10.1 and port 53 -vvv -c 500 -w /var/log/dns_investigation_143.88.255.10.pcap
- nc -zvw3 -u 10.0.10.1 53
- iptables -N DNS_RATE_LIMIT
- iptables -I FORWARD -s 143.88.255.10 -d 10.0.10.1 -p udp --dport 53 -j DNS_RATE_LIMIT
- iptables -I FORWARD -s 143.88.255.10 -d 10.0.10.1 -p tcp --dport 53 -j DNS_RATE_LIMIT
- iptables -A DNS_RATE_LIMIT -m hashlimit --hashlimit-name dns_throttle --hashlimit-above 5/sec --hashlimit-burst 15 --hashlimit-mode srcip -m limit --limit 2/min -j LOG --log-prefix '[IPTABLES-DNS-FLOOD]: '
- iptables -A DNS_RATE_LIMIT -m hashlimit --hashlimit-name dns_throttle --hashlimit-above 5/sec --hashlimit-burst 15 --hashlimit-mode srcip -j DROP
- iptables -A DNS_RATE_LIMIT -j ACCEPT