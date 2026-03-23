export const onRequest: PagesFunction = async () => {
  const response = await fetch(
    "https://mfs-backend-wvjp6xty2q-uc.a.run.app/api/sitemap.xml"
  );
  const xml = await response.text();
  return new Response(xml, {
    status: response.status,
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": "public, max-age=3600",
    },
  });
};
