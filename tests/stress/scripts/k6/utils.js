import http from "k6/http";
import { check } from "k6";
import { randomBytes, sha256 } from "k6/crypto";

export const BASE_URL = __ENV.BASE_URL || "http://localhost:8083";

const TOKEN = __ENV.SERVICE_API_TOKEN || "";
if (!TOKEN) {
  throw new Error(
    "SERVICE_API_TOKEN no definida: pasa --env SERVICE_API_TOKEN=... o exportala antes de correr k6.",
  );
}

const AUTH = { Authorization: `Bearer ${TOKEN}` };
const JSON_HEADERS = { ...AUTH, "Content-Type": "application/json" };

export function uniqueChecksum() {
  return sha256(randomBytes(16), "hex");
}

// Ciclo append-only de AUDA: crea un evento único, lista la página global y
// vuelve a leerlo por checksum. No hay PUT/DELETE (responden 405).
export function auditCycle() {
  const checksum = uniqueChecksum();
  const event = {
    action: "pdf.extract",
    entity_type: "document",
    checksum,
    performed_at: new Date().toISOString(),
    details: { source: "k6" },
  };

  const created = http.post(`${BASE_URL}/audit/logs`, JSON.stringify(event), {
    headers: JSON_HEADERS,
  });
  check(created, { "POST registra (201)": (r) => r.status === 201 });

  const listed = http.get(`${BASE_URL}/audit/logs?skip=0&limit=50`, {
    headers: AUTH,
  });
  check(listed, { "GET lista (200)": (r) => r.status === 200 });

  const byChecksum = http.get(`${BASE_URL}/audit/logs/checksum/${checksum}`, {
    headers: AUTH,
  });
  check(byChecksum, {
    "GET por checksum (200)": (r) => r.status === 200,
    "el listado contiene el evento": (r) => r.body.includes(checksum),
  });
}
