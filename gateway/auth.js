/**
 * JWT auth middleware.
 * Validates the token signature against Keycloak's JWKS endpoint and
 * extracts { username, role } onto req.user.
 *
 * For local/dev runs without Keycloak, set AUTH_MODE=insecure-dev and pass
 * headers `x-username` and `x-role` directly (never use this in the real
 * cluster demo -- only for quick local testing of the gateway logic).
 */
const jwt = require("jsonwebtoken");
const jwksClient = require("jwks-rsa");

const AUTH_MODE = process.env.AUTH_MODE || "keycloak"; // "keycloak" | "insecure-dev"
const KEYCLOAK_ISSUER = process.env.KEYCLOAK_ISSUER || "http://keycloak:8080/realms/hospital";
const KEYCLOAK_JWKS_URI =
  process.env.KEYCLOAK_JWKS_URI || `${KEYCLOAK_ISSUER}/protocol/openid-connect/certs`;

const jwks = jwksClient({
  jwksUri: KEYCLOAK_JWKS_URI,
  cache: true,
  cacheMaxAge: 10 * 60 * 1000,
});

function getKey(header, callback) {
  jwks.getSigningKey(header.kid, (err, key) => {
    if (err) return callback(err);
    callback(null, key.getPublicKey());
  });
}

function extractRole(decoded) {
  const roles = (decoded.realm_access && decoded.realm_access.roles) || [];
  const known = ["medico", "estagiario", "pesquisador"];
  return roles.find((r) => known.includes(r)) || roles[0] || "unknown";
}

function authMiddleware(req, res, next) {
  if (AUTH_MODE === "insecure-dev") {
    const username = req.header("x-username");
    const role = req.header("x-role");
    if (!username || !role) {
      return res.status(401).json({ error: "missing x-username/x-role dev headers" });
    }
    req.user = { username, role };
    return next();
  }

  const authHeader = req.header("authorization") || "";
  const token = authHeader.startsWith("Bearer ") ? authHeader.slice(7) : null;
  if (!token) {
    return res.status(401).json({ error: "missing bearer token" });
  }

  jwt.verify(token, getKey, { algorithms: ["RS256"] }, (err, decoded) => {
    if (err) {
      return res.status(401).json({ error: "invalid token", detail: err.message });
    }
    req.user = {
      username: decoded.preferred_username || decoded.sub,
      role: extractRole(decoded),
    };
    next();
  });
}

module.exports = { authMiddleware };
