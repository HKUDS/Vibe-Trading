import { copyFile, mkdir } from "node:fs/promises";

await mkdir(new URL("../dist/", import.meta.url), { recursive: true });
await copyFile(
  new URL("../src/loading.html", import.meta.url),
  new URL("../dist/loading.html", import.meta.url),
);
