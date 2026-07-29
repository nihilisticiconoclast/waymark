// Copy to site/config.js and fill in. config.js is gitignored.
//
// The OS Data Hub key is referrer-locked in the project settings and is delivered to the
// browser by design — this is the intended pattern for this API. It is not a secret, but it
// is also not free of consequence: lock it to your Pages origin and don't reuse it.
window.WAYMARK_CONFIG = {
  basemap: "opentopo",        // "opentopo" | "os-outdoor" | "os-leisure"
  osApiKey: "",               // required for os-outdoor and os-leisure
  cuddlyLampBase: "https://<user>.github.io/cuddly-lamp"
};
