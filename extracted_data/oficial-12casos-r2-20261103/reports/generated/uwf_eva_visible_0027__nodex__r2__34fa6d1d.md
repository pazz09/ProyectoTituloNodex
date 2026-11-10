## Diagnóstico

Falla operativa de red o desconfiguración de servicio DNS. Se identifican 262 intentos de conexión DNS (UDP/53) desde el host 143.88.255.10 hacia el resolver interno 10.0.10.1 finalizados en estado S0 (solicitud enviada sin respuesta recibida). La persistencia periódica hacia un único destino inaccesible, sumada a la ausencia de tráfico bidireccional, descarta actividad de ataque deliberado, exfiltración o tunelizado DNS. Se concluye que corresponde a reintentos automáticos por indisponibilidad o falla de enrutamiento hacia el servidor DNS.

## Evaluación del auditor

El diagnóstico es correcto. Los registros evidencian ráfagas periódicas de consultas DNS (UDP/53) desde el host 143.88.255.10 hacia 10.0.10.1 que finalizan en estado S0 (sin respuesta), mientras otros clientes de la red resuelven normalmente contra 143.88.1.1 (SF). El comportamiento concuerda con reintentos automáticos del resolver debido a un destino no alcanzable o fuera de servicio, tratándose de una falla operativa de red o desconfiguración sin indicios de actividad maliciosa ni exfiltración.

## Comandos de mitigación propuestos

- iptables -I INPUT 1 -s 143.88.255.10 -d 10.0.10.1 -p udp --dport 53 -m limit --limit 2/min -j LOG --log-prefix '[DNS_UNREACHABLE]: '
- iptables -I INPUT 2 -s 143.88.255.10 -d 10.0.10.1 -p udp --dport 53 -j REJECT --reject-with icmp-port-unreachable
- conntrack -D -s 143.88.255.10 -p udp --dport 53
- ss -ulnp 'sport = :53'
- ip route get 10.0.10.1