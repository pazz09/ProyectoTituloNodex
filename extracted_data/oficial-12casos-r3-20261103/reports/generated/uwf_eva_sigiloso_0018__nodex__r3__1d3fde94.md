## Diagnóstico

Se observan 266 intentos de conexión DNS (UDP/53) desde 143.88.255.10 hacia la IP privada 10.0.10.1 en estado Zeek S0 (tráfico unidireccional sin respuesta). Este comportamiento coincide con una desconfiguración de red en el host origen (servidor DNS mal configurado, inactivo o inalcanzable) o bloqueo por ACL/firewall entre ambos segmentos, descartando actividad maliciosa evidente. Como medidas correctivas proporcionales se recomienda: 1) Verificar la configuración del resolver DNS en el host 143.88.255.10 y redirigirlo a un DNS operativo (como 143.88.1.1); 2) Validar la alcanzabilidad y estado del servicio en 10.0.10.1:53; 3) Revisar reglas de filtrado o enrutamiento entre ambos direccionamientos.

## Evaluación del auditor

El diagnóstico es preciso. Los logs evidencian múltiples consultas DNS unidireccionales (S0) emitidas de manera periódica desde 143.88.255.10 hacia la IP privada 10.0.10.1 sin obtener respuesta, lo cual es indicativo de un problema de resolución de nombres, servidor DNS inaccesible o filtrado por firewall/enrutamiento. No se identifican patrones de C2, tunelización o exfiltración maliciosa.

## Comandos de mitigación propuestos

- iptables -A INPUT -p udp -s 143.88.255.10 -d 10.0.10.1 --dport 53 -m limit --limit 5/min --limit-burst 10 -j ACCEPT
- iptables -A INPUT -p udp -s 143.88.255.10 -d 10.0.10.1 --dport 53 -j LOG --log-prefix 'DNS_MISCONFIG_DROP: ' --log-level 4
- iptables -A INPUT -p udp -s 143.88.255.10 -d 10.0.10.1 --dport 53 -j DROP
- dig @10.0.10.1 localhost +time=2 +tries=1
- nc -zvu 10.0.10.1 53
- ip route get 10.0.10.1