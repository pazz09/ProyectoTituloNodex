## Diagnóstico

El tráfico analizado corresponde a un fallo operacional derivado de la falta de respuesta del servidor DNS 10.0.10.1. El host 143.88.255.10 emitió 262 solicitudes DNS hacia 10.0.10.1 en un intervalo de ~30 minutos, registrando un estado de conexión Zeek 'S0' (sin respuesta del destino) y 0 bytes de respuesta recibidos. Este comportamiento representa un bucle de reintentos por timeout de resolución ante un servicio inalcanzable o mal configurado, descartando actividad maliciosa deliberada o exfiltración.

## Evaluación del auditor

El diagnóstico es correcto. La evidencia muestra un patrón de reintentos continuos de consultas DNS UDP hacia la dirección 10.0.10.1 que no son respondidas (estado Zeek S0). Al mismo tiempo, otras consultas en la red hacia 143.88.1.1 se resuelven normalmente (SF), lo que confirma una falla de conectividad o servicio inalcanzable/mal configurado en 10.0.10.1 y no un incidente de seguridad ni actividad maliciosa.

## Comandos de mitigación propuestos

- iptables -I INPUT -p udp -s 143.88.255.10 --dport 53 -m hashlimit --hashlimit-name DNS_RATE --hashlimit-above 5/sec --hashlimit-burst 10 --hashlimit-mode srcip -j DROP
- iptables -A FORWARD -p udp -s 143.88.255.10 -d 10.0.10.1 --dport 53 -j REJECT --reject-with icmp-port-unreachable
- iptables -A INPUT -p udp -d 10.0.10.1 --dport 53 -j REJECT --reject-with icmp-port-unreachable
- systemctl status systemd-resolved
- resolvectl status