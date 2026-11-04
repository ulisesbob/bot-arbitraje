# Bot de alertas de arbitraje cripto (CriptoYa)

Consulta la API pública de [CriptoYa](https://criptoya.com) cada un minuto, compara
el precio de compra más barato (`totalAsk`) contra el de venta más caro (`totalBid`)
entre todos los exchanges, y cuando el spread supera el umbral manda una alerta
por Telegram y por consola.

No necesita instalar nada: solo Python 3.10 o superior.

## Correr

```bash
python arbitraje.py
```

Una sola pasada para probar:

```bash
python arbitraje.py --once
```

O doble clic en `iniciar.bat`.

## Configuración (`config.json`)

Se crea solo la primera vez. Campos:

| Campo | Qué hace | Default |
|---|---|---|
| `pares` | pares a vigilar (`coin/fiat` según CriptoYa) | usdt, usdc, dai, btc, eth contra ars y contra usd |
| `volumen` | monto en fiat para el cálculo de precios con comisión | 1000 |
| `umbral_pct` | spread mínimo para alertar | 1.5 |
| `intervalo_seg` | cada cuánto consulta | 60 |
| `max_antiguedad_seg` | descarta cotizaciones más viejas que esto | 600 |
| `cooldown_seg` | no repite la misma alerta (par + exchanges) durante este tiempo; se guarda en `cooldown.json` y sobrevive reinicios | 900 |
| `excluir_exchanges` | exchanges a ignorar en alertas, rulos y comandos; `"*p2p"` excluiría todos los P2P. Por defecto los P2P entran, marcados con 👥 y una advertencia de verificar la cotización | `[]` |
| `max_desvio_pct` | descarta precios alejados más de esto de la mediana (ofertas basura de P2P); `0` apaga el filtro | 5.0 |
| `rulos` | buscar rulos de 3 o 4 patas (pesos → dólar/stablecoin → … → pesos) | `true` |
| `umbral_rulo_pct` | rendimiento mínimo de un rulo para alertar | 2.0 |
| `volumen_rulo` | monto en pesos sobre el que se calcula la ganancia del rulo | 100000 |
| `max_patas` | largo máximo del rulo | 4 |
| `telegram_token` / `telegram_chat_id` | credenciales de Telegram | vacío |

Si dejás esos campos vacíos, se usan las variables de entorno `TELEGRAM_BOT_TOKEN` y
`TELEGRAM_CHAT_ID`. Lo que está en el archivo siempre tiene prioridad.

## Telegram

1. Hablale a `@BotFather` en Telegram, mandá `/newbot`, elegí nombre, y copiá el token.
2. Abrí un chat con tu bot nuevo y mandale cualquier mensaje.
3. Entrá a `https://api.telegram.org/bot<TOKEN>/getUpdates` en el navegador y copiá
   el número que aparece en `"chat":{"id":...}`.
4. Pegá token y chat id en `config.json` y probá:

```bash
python arbitraje.py --test-telegram
```

Si no configurás Telegram, las alertas salen solo por consola.

## Comandos de Telegram

Con Telegram configurado, el bot también responde mensajes (tipeá `/` y aparece el menú):

| Comando | Qué responde |
|---|---|
| `/arbitraje` | mejor spread de cada par ahora, marcando los que superan el umbral |
| `/rulos` | los 5 mejores rulos de 3 o 4 patas ahora, superen o no el umbral |
| `/dolar` | todas las formas de comprar dólares ordenadas de más barata a más cara (oficial, blue, MEP, CCL, cripto, tarjeta) y la stablecoin más barata por exchange |
| `/btc` `/eth` `/usdt` `/usdc` `/dai` | los 3 exchanges más baratos para comprar y los 3 mejores para vender, en pesos |
| `/umbral` | muestra el umbral de alerta; `/umbral 1.5` lo cambia y lo guarda en `config.json` |
| `/ayuda` | la lista de comandos |

Solo responde al chat configurado en `telegram_chat_id`; a cualquier otro lo ignora.

En el despliegue actual los comandos los responde al instante un webhook en Vercel y las
alertas las manda GitHub Actions cada 10 minutos. Ver [DEPLOY.md](DEPLOY.md).

## ¿Tiene que estar la compu prendida?

Sí: el bot es un proceso Python que corre en tu máquina. Si la apagás o cerrás la
ventana, deja de vigilar. Opciones para que corra solo:

- **Tarea programada de Windows** que lo arranque al iniciar sesión (sigue dependiendo
  de que la compu esté prendida).
- **Un servidor gratuito o barato** (Oracle Cloud Free Tier, Fly.io, Railway, una Raspberry
  Pi en tu casa). Copiás la carpeta, instalás Python y lo corrés igual que acá.
  No usa ninguna librería externa, así que no hay nada más que instalar.

## Rulos (ciclos de 3 o 4 patas)

Además del arbitraje simple, el bot busca ciclos que empiezan y terminan en pesos pasando
por dólares y stablecoins, por ejemplo: comprar dólar oficial en el banco, con esos dólares
comprar USDT en un exchange, y vender el USDT por pesos en otro. Usa el dólar oficial y el
MEP de CriptoYa como patas bancarias, y las cotizaciones de USDT, USDC y DAI contra pesos
y contra dólares como patas cripto. Para cada secuencia elige el mejor exchange por pata.

Cuando un rulo supera `umbral_rulo_pct` manda una alerta con cada pata, su precio, si es
P2P, y advertencias sobre transferencias y la pata bancaria. Cuando deja de superar el
umbral avisa que se cerró, a cuánto llegó y cuánto duró. El estado vive en `rulos.json`.

Advertencia: estos rulos muestran precios publicados, no ejecuciones garantizadas. Los P2P
dependen de encontrar contraparte, mover dólares entre un exchange y un banco o broker tiene
costos y demoras, y la compra de dólar oficial tiene reglas y límites propios.

## Qué significa la alerta

```
🚨 Arbitraje USDT/ARS  +1.35%
Comprar en binancep2p a 1,669.33
Vender en fiwind a 1,691.90
Ganancia bruta sobre 1,000 ARS: ~14 ARS
```

Los precios ya incluyen las comisiones de trading que reporta CriptoYa, pero **no**
incluyen el costo de mover la cripto o el fiat entre exchanges, ni el tiempo que tarda.
Un spread del 1% suele evaporarse después de retiros y transferencias: subí `umbral_pct`
según tus costos reales.

## Tests

```bash
python -m pytest -q test_arbitraje.py
```
