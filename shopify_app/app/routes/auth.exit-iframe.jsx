export async function loader() {
  return new Response(
    `<!DOCTYPE html>
<html>
<head>
  <title>Hello World</title>
</head>
<body>
  <div style="padding: 20px; font-size: 24px; font-weight: bold;">
    Hello World!
  </div>
</body>
</html>`,
    {
      status: 200,
      headers: {
        "Content-Type": "text/html",
      },
    }
  );
}
