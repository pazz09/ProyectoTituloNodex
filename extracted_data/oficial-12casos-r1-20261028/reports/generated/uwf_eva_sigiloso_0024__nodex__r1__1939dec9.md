## Diagnóstico

Se observan 264 conexiones DNS (UDP/53) salientes desde el host 143.88.255.10 hacia 10.0.10.1 en estado 'S0' (sin respuesta del destino) a lo largo de 30 minutos. La dirección de destino (10.0.10.1) corresponde a un segmento privado RFC 1918, inalcanzable o con el servicio DNS caído/filtrado por firewall, lo que ocasiona la acumulación de reintentos fallidos sistemáticos. Dado que el destino es un resolver interno privado no respondiente y el patrón de paquetes presenta tamaños uniformes típicos de consultas no atendidas, el comportamiento apunta principalmente a una desconfiguración operativa (servidor DNS primario inaccesible) en lugar de un canal encubierto o exfiltración activa, aunque el tráfico persistente debe ser mitigado corrigiendo el puntero DNS del host hacia un servidor resolutor válido o bloqueando la ruta si el host no debe enrutar hacia dicho segmento.

## Evaluación del auditor

El diagnóstico es correcto. Se observa un volumen continuo y periódico de consultas DNS salientes (UDP/53) desde 143.88.255.10 hacia la IP privada 10.0.10.1 que no obtienen respuesta (estado S0). El comportamiento responde a una anomalía puramente operativa producto de un resolutor DNS inaccesible o mal configurado en el cliente, descartándose actividad maliciosa, C2 o exfiltración.

## Comandos de mitigación propuestos

- iptables -I OUTPUT -d 10.0.10.1 -p udp --dport 53 -j REJECT --reject-with icmp-port-unreachable
- iptables -I OUTPUT -d 10.0.10.1 -p tcp --dport 53 -j REJECT --reject-with tcp-reset
- iptables -I FORWARD -s 143.88.255.10 -d 10.0.10.1 -p udp --dport 53 -j DROP
- ip route add unreachable 10.0.10.1/32
- sed -i.bak '/nameserver 10.0.10.1/d' /etc/resolv.conf