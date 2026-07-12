import { app } from "electron";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

export type StoragePaths = {
  root: string;
  database: string;
  uploads: string;
  extracts: string;
  media: string;
  temp: string;
  backups: string;
};

export function getStoragePaths(): StoragePaths {
  const root = app.getPath("userData");
  return {
    root,
    database: join(root, "database.sqlite"),
    uploads: join(root, "uploads"),
    extracts: join(root, "extracts"),
    media: join(root, "media"),
    temp: join(root, "temp"),
    backups: join(root, "backups"),
  };
}

export function ensureStorage(): StoragePaths {
  const paths = getStoragePaths();
  for (const path of Object.values(paths)) {
    if (path !== paths.database) mkdirSync(path, { recursive: true });
  }
  return paths;
}
