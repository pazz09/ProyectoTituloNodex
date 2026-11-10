## Diagnóstico

Falla de conectividad o desconfiguración de resolución DNS operativa hacia un servidor no disponible (10.0.10.1)

## Evaluación del auditor

Se observa un volumen sostenido de solicitudes DNS salientes (puerto 53/UDP) desde el host 143.88.255.10 con destino a 10.0.10.1 en intervalos constantes de aproximadamente 30 segundos, finalizando todas en estado Zeek S0 (sin respuesta). No hay evidencia de exfiltración, túneles DNS establecidos ni actividad maliciosa confirmada en el contenido de los paquetes; el comportamiento corresponde característicamente a un cliente o servicio reintentando consultas contra un servidor DNS inalcanzable o fuera de servicio.

## Comandos de mitigación propuestos

- ping -c 4 10.0.10.1
- dig @10.0.10.1 localhost
- cat /etc/resolv.conf
- journalctl -u systemd-resolved -n 50 --no-pager