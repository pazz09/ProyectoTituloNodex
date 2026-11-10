## Diagnóstico

Se observa un patrón recurrente de tráfico DNS UDP dirigido desde el host 143.88.255.10 hacia la dirección 10.0.10.1 (puerto 53) con estado de conexión 'S0' constante (264 eventos unidireccionales sin respuesta del destino durante un lapso de 30 minutos). Dado que otros clientes en el mismo segmento (como 143.88.1.51) resuelven DNS normalmente a través de servidores internos (143.88.1.1) y consultas raíz, el comportamiento corresponde principalmente a un fallo de infraestructura o error de configuración de red (servidor DNS no alcanzable, ruta inexistente hacia 10.0.10.1 o servicio inactivo/bloqueado por firewall perimetral), sin evidencia directa de exfiltración o balizamiento C2 complejo en esta capa.

## Evaluación del auditor

El diagnóstico es correcto. La evidencia muestra un patrón continuo y periódico de solicitudes DNS dirigidas desde 143.88.255.10 a una IP privada inalcanzable (10.0.10.1:53) que resultan invariablemente en estado S0 (sin respuesta SYN-ACK / unidireccional UDP). Al mismo tiempo, otros hosts del entorno resuelven DNS normalmente (SF) con el servidor interno 143.88.1.1. No se aprecia carga útil maliciosa, canales encubiertos ni balizamiento C2 confirmado, tratándose de una anomalía estrictamente operativa o de configuración de red.

## Comandos de mitigación propuestos

- iptables -I FORWARD -s 143.88.255.10 -d 10.0.10.1 -p udp --dport 53 -m limit --limit 5/min -j LOG --log-prefix '[DNS_MISCONFIG]: '
- iptables -I FORWARD 2 -s 143.88.255.10 -d 10.0.10.1 -p udp --dport 53 -j REJECT --reject-with icmp-port-unreachable
- iptables -I INPUT -s 143.88.255.10 -d 10.0.10.1 -p udp --dport 53 -j REJECT --reject-with icmp-port-unreachable
- ip route add unreachable 10.0.10.1/32