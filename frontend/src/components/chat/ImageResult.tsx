import type { FC } from "react";
import { useTranslation } from "react-i18next";

export const ImageResult: FC<{ images: Array<{ path: string; mime_type?: string; alt?: string; download_url?: string }> }> = ({ images }) => {
  const { t } = useTranslation();
  return <div className="grid gap-2 sm:grid-cols-2">{images.map((image, index) => <figure key={`${image.path}-${index}`}><img className="max-h-96 rounded-lg border object-contain" src={image.download_url || image.path} alt={image.alt || t("agent.toolResultImageAlt")} /><figcaption className="text-xs text-muted-foreground">{image.path}</figcaption></figure>)}</div>;
};
