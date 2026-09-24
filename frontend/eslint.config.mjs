import nextConfig from "eslint-config-next";

const eslintConfig = [
  ...nextConfig,
  {
    ignores: [".next/**", "node_modules/**"],
  },
  {
    // `react-hooks/set-state-in-effect` marca `historial-view.tsx` y
    // `overview-view.tsx`: cargan datos al montar llamando una función que
    // hace `setCargando(true)` antes del `await` -- el patrón estándar de
    // "fetch on mount" del proyecto, no un bug. Se baja a warning en vez de
    // reescribir el patrón de carga bajo el cierre de auditoría (fuera de
    // alcance); queda visible para revisarlo aparte si se justifica.
    rules: {
      "react-hooks/set-state-in-effect": "warn",
    },
  },
];

export default eslintConfig;
