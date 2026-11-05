import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

export const wiki = fileURLToPath(new URL("../../wiki/", import.meta.url));
for (const script of ["prerender_docs.mjs", "gen_sitemap.mjs"]) {
  execFileSync(process.execPath, [`scripts/${script}`], { cwd: wiki, stdio: "inherit" });
}
