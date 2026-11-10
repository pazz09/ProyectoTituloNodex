## Diagnóstico

Falla operativa de conectividad DNS: el host 143.88.255.10 envía consultas DNS periódicas (cada ~30 segundos) hacia el servidor 10.0.10.1 sin recibir respuesta (estado S0), lo cual corresponde a reintentos de resolución de nombres hacia un servidor inaccesible o inactivo.

## Evaluación del auditor

Se observa un patrón reiterado de consultas DNS UDP hacia la IP 10.0.10.1 en intervalos constantes de aproximadamente 30 segundos, totalizando 261 intentos fallidos con estado S0 (sin respuesta). No se observa tráfico de exfiltración, explotación ni escaneo de puertos disperso; otros hosts en la red (143.88.1.51 y 143.88.1.53) resuelven DNS normalmente a través de 143.88.1.1 con estado SF. La evidencia apunta a un problema de enrutamiento o servicio DNS inactivo en 10.0.10.1.

## Comandos de mitigación propuestos

- ping -c 4 10.0.10.1
- traceroute 10.0.10.1
- cat /etc/resolv.conf
- systemctl status systemd-resolved