## Diagnóstico

Se observa un patrón anómalo de tráfico de alta frecuencia originado en la IP 143.88.255.10 con destino al servidor DNS 10.0.10.1 en el puerto 53/UDP, acumulando 262 eventos con estado de conexión 'S0' (conexiones iniciadas sin respuesta del servidor) en un lapso de 30 minutos. Este comportamiento es característico de un sondeo masivo, un intento de denegación de servicio por saturación de consultas DNS o intentos fallidos de comunicación de comando y control / tunneling DNS (T1071.004), los cuales están fracasando o siendo descartados por el destino. Se recomienda aislar temporalmente la IP 143.88.255.10 y analizar las cargas útiles (payload/queries) para descartar herramientas de tunelizado o exfiltración.

## Evaluación del auditor

Se observa un patrón anómalo de consultas DNS sin respuesta (estado S0) desde 143.88.255.10 hacia 10.0.10.1. Sin embargo, el volumen total registrado (aproximadamente 262 consultas en 30 minutos, con ráfagas periódicas de 3 a 7 paquetes cada exactamente ~30.25 segundos) corresponde a una tasa promedio menor a 0.15 consultas por segundo. Este comportamiento es inconsistente con un ataque de denegación de servicio (DoS) o sondeo masivo agresivo, y refleja típicamente reintentos automáticos de resolución de un servicio o cliente con un servidor DNS inalcanzable o mal configurado (en contraste con otros hosts de la red que consultan exitosamente a 143.88.1.1). No existe evidencia de actividad maliciosa ni de C2/tunelizado activo.

## Comandos de mitigación propuestos

- iptables -I INPUT 1 -s 143.88.255.10 -j LOG --log-prefix "DNS_SUSPECT_BLOCK: " --log-level 4
- iptables -I INPUT 2 -s 143.88.255.10 -j DROP
- conntrack -D -s 143.88.255.10
- ufw insert 1 deny from 143.88.255.10 to any