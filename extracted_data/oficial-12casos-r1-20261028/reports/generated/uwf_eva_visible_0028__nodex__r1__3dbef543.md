## Diagnóstico

El tráfico observado entre 143.88.255.10 y 10.0.10.1 (261 eventos DNS, todos registrados como intentos fallidos con estado S0/sin respuesta) es consistente con un fallo operativo por reintentos continuos hacia un servidor DNS inalcanzable, fuera de servicio o mal configurado, descartando actividad maliciosa activa. Medidas recomendadas: 1) Verificación no disruptiva: inspeccionar la configuración de red y resolutores DNS en el host 143.88.255.10 (resolv.conf o configuración de interfaz), verificar la conectividad de capa 3 hacia 10.0.10.1 mediante ping/traceroute pasivo, y capturar queries locales para identificar qué servicio o proceso genera las peticiones. 2) Contención y remediación no disruptiva: reconfigurar el cliente para utilizar un servidor DNS operativo y validado en la red (como 143.88.1.1, que muestra actividad normal en el lote) o corregir la ruta de red hacia 10.0.10.1, evitando bloqueos por firewall que puedan degradar servicios legítimos en el host.

## Evaluación del auditor

El diagnóstico es preciso. Se observan múltiples consultas DNS continuas hacia la dirección 10.0.10.1 que no reciben respuesta (estado S0), mientras que otros clientes resuelven satisfactoriamente contra 143.88.1.1. Esto corresponde a un fallo operativo de configuración o conectividad de red hacia el servidor DNS especificado, y no a una intrusión o ataque activo.

## Comandos de mitigación propuestos

- cat /etc/resolv.conf
- resolvectl status 2>/dev/null || nmcli dev show | grep DNS
- ping -c 4 -W 2 10.0.10.1
- traceroute -n -m 15 10.0.10.1 || tracepath -n 10.0.10.1
- ss -tupan | grep ':53 '
- tcpdump -nn -i any host 10.0.10.1 and port 53 -c 10
- cp /etc/resolv.conf /etc/resolv.conf.bak
- sed -i 's/nameserver 10.0.10.1/nameserver 143.88.1.1/' /etc/resolv.conf
- dig @143.88.1.1 localhost +short