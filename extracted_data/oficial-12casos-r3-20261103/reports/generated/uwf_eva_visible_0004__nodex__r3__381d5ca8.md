## Diagnóstico

Se identifica un patrón anómalo de tráfico de red DNS de alta intensidad concentrado principalmente en la IP de origen 143.88.255.10 enviando 213 solicitudes UDP/53 hacia 10.0.10.1 que no reciben respuesta adecuada (estado de conexión S0/intentos fallidos), además de un flujo no resuelto de 60 eventos entre 143.88.18.12 y 143.88.18.11. Este comportamiento recurrente y unidireccional sobre el protocolo DNS es compatible con técnicas de Command and Control o exfiltración mediante DNS (T1071.004), o bien con un intento de denegación de servicio/escaneo de resolución DNS interna. Se recomienda aislar la IP 143.88.255.10 e inspeccionar la carga útil de las consultas para descartar tunelización DNS.

## Evaluación del auditor

El diagnóstico acierta al señalar las consultas repetitivas DNS de 143.88.255.10 hacia 10.0.10.1 con estado S0 cada ~30 segundos. Sin embargo, comete un error crítico al interpretar el tráfico de 143.88.18.12 hacia 143.88.18.11 como DNS; en realidad se trata de un escaneo de puertos TCP sistemático sobre servicios conocidos (21, 22, 23, 80, 143, 443, 445, 3389, 5900, etc.) con flags SH (SYN-half/scans). Debido a esto, la mitigación propuesta para 143.88.18.12 (bloqueo exclusivo de udp/53) resulta completamente ineficaz para contener el escaneo.

## Comandos de mitigación propuestos

- iptables -I INPUT 1 -s 143.88.255.10 -j DROP
- iptables -I FORWARD 1 -s 143.88.255.10 -j DROP
- ufw insert 1 deny from 143.88.255.10 to any
- iptables -I INPUT 2 -s 143.88.18.12 -p udp --dport 53 -j DROP
- iptables -I INPUT 3 -p udp --dport 53 -m hashlimit --hashlimit-name dns_rate_limit --hashlimit-above 20/sec --hashlimit-burst 40 --hashlimit-mode srcip -j DROP
- nohup tcpdump -i any -nn -s 0 -vvv 'port 53 and (host 143.88.255.10 or host 143.88.18.12)' -w /var/log/dns_suspicious_payload.pcap -c 1000 >/dev/null 2>&1 &
- netfilter-persistent save