/* Django's CSRF token, sent as the X-CSRFToken header on every call to the app's API. */
function csrfToken() {
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : '';
}
