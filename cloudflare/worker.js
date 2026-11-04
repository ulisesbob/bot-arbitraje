// Reloj del bot: cada minuto le pide al bot en Vercel que haga una pasada y guarda el
// estado (alertas ya mandadas, rulos abiertos) en Cloudflare KV.
//
// Variables (wrangler.toml / secrets):
//   SCAN_URL     https://bot-arbitraje-xi.vercel.app/api/scan
//   SCAN_SECRET  el mismo WEBHOOK_SECRET de Vercel  (wrangler secret put SCAN_SECRET)
//   ESTADO       binding al namespace KV

const CLAVE = "estado";
const GUARDAR_CADA_MS = 10 * 60 * 1000; // escribir KV aunque no cambie, para que /ultimo muestre vida

function limpiar(v) {
  return (v || "").replace(/^﻿/, "").trim();
}

async function pasada(env) {
  const guardado = (await env.ESTADO.get(CLAVE, "json")) || {};
  const estado = guardado.estado || {};
  const inicio = Date.now();

  const resp = await fetch(env.SCAN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Scan-Secret": limpiar(env.SCAN_SECRET) },
    body: JSON.stringify({ estado }),
  });
  const texto = await resp.text();
  if (!resp.ok) {
    console.error(`scan ${resp.status}: ${texto.slice(0, 200)}`);
    return { ok: false, status: resp.status, detalle: texto.slice(0, 200) };
  }
  const r = JSON.parse(texto);
  const nuevo = {
    estado: r.estado,
    ultimo: new Date().toISOString(),
    ms: Date.now() - inicio,
    alertas: r.alertas,
    rulos_abiertos: r.rulos_abiertos,
    resumen: r.resumen,
  };
  const cambio = JSON.stringify(r.estado) !== JSON.stringify(estado);
  const viejo = !guardado.ultimo || Date.now() - Date.parse(guardado.ultimo) > GUARDAR_CADA_MS;
  if (cambio || viejo) {
    await env.ESTADO.put(CLAVE, JSON.stringify(nuevo)); // KV gratis: 1000 escrituras/dia, por eso no siempre
  }
  console.log(`ok ${nuevo.ms}ms alertas=${r.alertas} rulos=${r.rulos_abiertos} guardado=${cambio || viejo}`);
  return { ok: true, ...nuevo, guardado: cambio || viejo };
}

export default {
  // Cron: ver [triggers] en wrangler.toml
  async scheduled(event, env, ctx) {
    ctx.waitUntil(pasada(env));
  },

  // HTTP: /ultimo muestra la ultima corrida; /run?secret=... dispara una pasada a mano
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/run") {
      if (limpiar(url.searchParams.get("secret")) !== limpiar(env.SCAN_SECRET)) {
        return new Response("secreto invalido", { status: 403 });
      }
      const r = await pasada(env);
      return Response.json(r);
    }
    if (url.pathname === "/ultimo") {
      const g = (await env.ESTADO.get(CLAVE, "json")) || {};
      const { estado, ...resto } = g;
      return Response.json({ ...resto, cooldowns: Object.keys(estado?.cooldown || {}).length });
    }
    return new Response("bot arbitraje: reloj activo. /ultimo para ver la ultima corrida.");
  },
};
