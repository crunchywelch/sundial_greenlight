# Enabling a full-page Customer Account UI extension

Adding a new full-page customer-account extension (target
`customer-account.page.render`, e.g. "My Cables", "Wholesale Order Form") takes
**three** steps. Deploying is only the first. Miss the middle one and the page
loads with a generic **"There's a problem loading this page. Check the URL or try
again in a few minutes"** error, even though the bundle, registration, uid, and
menu link are all correct. The extension runs in a sandboxed worker, so the real
cause never shows in the browser console. This is not a code/registration/limit
problem and no amount of redeploying fixes it.

## The three steps

1. **Deploy the extension.** `shopify app deploy` (the user runs this, not Claude,
   because it needs interactive Partner auth). See
   `.claude/.../project_shopify_app_deploy_process`.

2. **Add it as a PAGE in the customer-account theme config** (the buried, easy-to-
   forget step):

   > Shopify admin → **Settings → Checkout → Configurations → _(your
   > configuration)_ → Edit → Checkout Menu → Profile → Main** → it shows an error
   > there and lets you **select/add the page** for the extension.

3. **Add the menu link** in the checkout & accounts editor so buyers can reach it
   (Settings → Checkout → Customize → a Customer account page → header menu → add
   link → pick the app page).

## Gotchas

- Steps 2 and 3 are **per extension**. Each new page extension must be added to the
  Profile → Main page config individually.
- If you temporarily change an existing page extension's target (e.g. flip it to a
  block and back), it may drop out of the Profile → Main config and need
  re-adding via step 2, even though its registration/uid is unchanged.
- Symptom of a missing step 2: the page errors while other, already-enabled page
  extensions (like My Cables) render fine for the same customer.
