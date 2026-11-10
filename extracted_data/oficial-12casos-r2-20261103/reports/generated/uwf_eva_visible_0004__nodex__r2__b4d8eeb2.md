## Diagnóstico

Se observa un comportamiento anómalo de red caracterizado por 279 eventos críticos en un lapso de 25 minutos. La IP 143.88.255.10 emitió 213 solicitudes DNS (UDP/53) hacia el servidor interno 10.0.10.1 con estado de conexión S0 (sin respuesta), lo cual es consistente con intentos de comunicación de comando y control o tunelización encubierta abusando del protocolo DNS (T1071.004), o bien un intento de denegación de servicio/escaneo por DNS. Paralelamente, la IP 143.88.18.12 registra 60 conexiones fallidas directas hacia 143.88.18.11, sugiriendo actividad de escaneo o movimiento lateral no autorizado. Se recomienda el aislamiento inmediato de los hosts 143.88.255.10 y 143.88.18.12, la revisión de los logs detallados de DNS (dns.log de Zeek) para inspeccionar las consultas específicas generadas, y verificar la integridad de 143.88.18.11.

## Evaluación del auditor

Se confirma actividad anómala maliciosa consistente en un escaneo de puertos TCP (Network Service Discovery) originado desde 143.88.18.12 hacia 143.88.18.11 a través de múltiples servicios críticos (SSH, RDP, SMB, VNC, HTTP, Telnet, bases de datos) en estado SH (half-open). Paralelamente, se observan ráfagas persistentes de paquetes DNS dirigidos a 10.0.10.1 sin respuesta (S0) desde 143.88.255.10. El diagnóstico es acertado en identificar la naturaleza no autorizada del tráfico y las medidas de contención/aislamiento son procedentes.

## Comandos de mitigación propuestos

- iptables -I INPUT -s 143.88.255.10 -j DROP
- iptables -I FORWARD -s 143.88.255.10 -j DROP
- iptables -I OUTPUT -d 143.88.255.10 -j DROP
- iptables -I INPUT -s 143.88.18.12 -j DROP
- iptables -I FORWARD -s 143.88.18.12 -j DROP
- iptables -I OUTPUT -d 143.88.18.12 -j DROP
- conntrack -D -s 143.88.255.10 2>/dev/null || true
- conntrack -D -s 143.88.18.12 2>/dev/null || true
- zeek-cut id.orig_h id.resp_h query qtype_name < /opt/zeek/logs/current/dns.log | grep '143.88.255.10' | head -n 50