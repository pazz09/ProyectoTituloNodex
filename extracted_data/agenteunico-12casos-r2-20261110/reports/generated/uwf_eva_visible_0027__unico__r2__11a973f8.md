## Diagnóstico

Falla operativa de conectividad o resolucion DNS persistente desde 143.88.255.10 hacia 10.0.10.1 sin indicios de actividad maliciosa.

## Evaluación del auditor

Se observan 262 intentos fallidos de conexion UDP/53 (estado Zeek S0) desde la IP 143.88.255.10 dirigidos hacia el resolver 10.0.10.1 a intervalos regulares de aproximadamente 30 segundos, sin recibir respuesta. Paralelamente, otros hosts del entorno (143.88.1.51 y 143.88.1.53) resuelven DNS exitosamente contra 143.88.1.1 (estado SF) y se observa tráfico habitual de resolución raíz y broadcast/multicast (DHCPv6, LLMNR, NetBIOS). No hay evidencia de tunelado, exfiltración ni escaneo malicioso; el patrón se ajusta a un resolver DNS inaccesible o mal configurado en el cliente.

## Comandos de mitigación propuestos

- cat /etc/resolv.conf
- ping -c 4 10.0.10.1
- traceroute 10.0.10.1
- dig @10.0.10.1 localhost +time=2 +tries=1
- tcpdump -nn -i any host 10.0.10.1 and port 53