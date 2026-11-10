## Diagnóstico

Fallo operativo en la infraestructura de resolución DNS. El host interno 143.88.255.10 registra 266 intentos fallidos hacia el servidor upstream 10.0.10.1 en el puerto 53/UDP con estado de conexión S0 (solicitudes enviadas sin respuesta), confirmando la inalcanzabilidad del resolver y la degradación del servicio DNS interno sin indicios de actividad maliciosa.

## Evaluación del auditor

El diagnóstico es preciso. Los registros de Zeek muestran que el host 143.88.255.10 intenta de forma periódica y repetida contactar al resolver DNS 10.0.10.1 en el puerto 53/UDP, obteniendo invariablemente un estado S0 (solicitud enviada sin respuesta). Paralelamente, otros equipos en la subred resuelven correctamente contra 143.88.1.1 (estado SF). No se aprecian patrones de exfiltración, C2 ni abuso de túneles DNS, correspondiendo a un problema netamente operativo de conectividad o indisponibilidad del servidor DNS destino.

## Comandos de mitigación propuestos

- iptables -t nat -I OUTPUT -p udp -d 10.0.10.1 --dport 53 -j DNAT --to-destination 1.1.1.1:53
- iptables -t nat -I OUTPUT -p tcp -d 10.0.10.1 --dport 53 -j DNAT --to-destination 1.1.1.1:53
- iptables -I OUTPUT -p udp --dport 53 -j ACCEPT
- iptables -I OUTPUT -p tcp --dport 53 -j ACCEPT
- sed -i '1inameserver 1.1.1.1' /etc/resolv.conf
- systemctl restart systemd-resolved 2>/dev/null || true