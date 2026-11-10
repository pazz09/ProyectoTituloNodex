## Diagnóstico

Falla operativa de conectividad DNS hacia un servidor de nombres inaccesible o no responsivo

## Evaluación del auditor

Se observa un flujo persistente y periódico (aproximadamente cada 30 segundos) de peticiones DNS (puerto 53/UDP) originadas desde la dirección 143.88.255.10 hacia la IP privada 10.0.10.1. Todas las conexiones finalizan con estado 'S0' (sin respuesta del servidor), acumulando 264 intentos fallidos. Simultáneamente, otros equipos de la red resuelven DNS de forma exitosa contra 143.88.1.1 (estado 'SF'). No existen indicios de actividad maliciosa, C2 ni exfiltración; la evidencia apunta a una desconfiguración de red, fallo de enrutamiento o servicio DNS caído en 10.0.10.1.

## Comandos de mitigación propuestos

- ping -c 4 10.0.10.1
- traceroute 10.0.10.1
- dig @10.0.10.1 localhost +time=2
- cat /etc/resolv.conf
- systemctl status systemd-resolved