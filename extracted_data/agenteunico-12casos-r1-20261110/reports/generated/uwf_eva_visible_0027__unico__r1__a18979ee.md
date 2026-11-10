## Diagnóstico

Falla operativa y anomalía de tráfico DNS no respondido hacia un resolver inalcanzable

## Evaluación del auditor

Se observa un patrón anómalo y repetitivo originado en el host 143.88.255.10, el cual envía ráfagas periódicas de consultas DNS (puerto UDP 53) cada 30 segundos aproximadamente hacia la dirección privada 10.0.10.1, acumulando 262 conexiones en estado S0 (sin respuesta del servidor). En contraste, otros clientes de la red (como 143.88.1.51 y 143.88.1.53) resuelven DNS de manera exitosa (estado SF) a través de 143.88.1.1. No se evidencia tráfico de comando y control exitoso ni exfiltración comprobable debido a la ausencia total de respuestas; la evidencia apunta principalmente a un problema de configuración de red, cliente apuntando a un servidor DNS fuera de servicio o una ruta inalcanzable.

## Comandos de mitigación propuestos

- cat /etc/resolv.conf
- systemd-resolve --status
- ping -c 4 10.0.10.1
- traceroute 10.0.10.1
- iptables -A OUTPUT -d 10.0.10.1 -p udp --dport 53 -j REJECT