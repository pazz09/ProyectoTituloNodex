## Diagnóstico

Se observa un volumen anómalo y concentrado de tráfico DNS hacia el servidor interno 10.0.10.1:53, originado predominantemente por la IP 143.88.255.10 con 266 intentos fallidos o no respondidos (estado de conexión S0 en UDP). Este comportamiento es consistente con un sondeo agresivo, intento de denegación de servicio (DNS flood) o un canal de comunicación encubierto/tunelado DNS no operativo (T1071.004). Se recomienda bloquear temporalmente las solicitudes de 143.88.255.10 en el cortafuegos/resolver, aislar el host de origen para análisis forense e inspeccionar la longitud y entropía de las consultas de nombres de dominio.

## Evaluación del auditor

Se observa un patrón anómalo de tráfico de red consistente en intentos periódicos de conexión DNS UDP hacia la dirección IP 10.0.10.1 en el puerto 53 que finalizan sin respuesta (estado S0). Sin embargo, el volumen total de peticiones (aproximadamente 266 en más de 30 minutos, con intervalos regulares de 30 segundos) corresponde al comportamiento estándar de reintentos y tiempo de espera de un resolver o cliente DNS cuando su servidor configurado no responde o es inalcanzable. Descartar un ataque de denegación de servicio (DNS flood) es claro debido a la bajísima tasa de paquetes (~8 paquetes por minuto). Tampoco existe evidencia de tunelado DNS ni compromiso, ya que no hay registros de carga útil o consultas completadas exitosamente. El diagnóstico original sobrestima la gravedad sugiriendo DoS y aislamiento forense ante lo que evidencia ser un problema operativo de resolución o enrutamiento.

## Comandos de mitigación propuestos

- iptables -I INPUT 1 -s 143.88.255.10 -j LOG --log-prefix "DNS_ABUSE_DROP: " --log-level 4
- iptables -I INPUT 2 -s 143.88.255.10 -p udp --dport 53 -j DROP
- iptables -I INPUT 3 -s 143.88.255.10 -p tcp --dport 53 -j DROP
- iptables -I INPUT 4 -s 143.88.255.10 -j DROP
- conntrack -D -s 143.88.255.10
- ufw insert 1 deny from 143.88.255.10 to 10.0.10.1 port 53
- tcpdump -i any -nn -s0 host 143.88.255.10 and port 53 -w /var/log/dns_incident_143.88.255.10.pcap -c 1000 &