// Bundles the dashboard cards into one module inside the integration, which
// serves it to the frontend (see custom_components/wow_blizzard/frontend.py).
import * as esbuild from "esbuild";
import { readFileSync } from "node:fs";

const manifest = JSON.parse(readFileSync("../custom_components/wow_blizzard/manifest.json", "utf8"));
const watch = process.argv.includes("--watch");

const options = {
  entryPoints: ["src/index.ts"],
  bundle: true,
  format: "esm",
  target: "es2021",
  minify: !watch,
  sourcemap: watch ? "inline" : false,
  outfile: "../custom_components/wow_blizzard/www/wow-cards.js",
  define: { __VERSION__: JSON.stringify(manifest.version) },
  legalComments: "eof",
  logLevel: "info",
};

if (watch) {
  await (await esbuild.context(options)).watch();
} else {
  await esbuild.build(options);
}
