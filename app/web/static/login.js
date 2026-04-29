const hint = document.getElementById("hint");
const csrfTokenInput = document.getElementById("csrf-token");

// Get CSRF token from cookie
function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
  return null;
}

// Set CSRF token from cookie on page load
const csrfToken = getCookie('csrf_token');
if (csrfToken && csrfTokenInput) {
  csrfTokenInput.value = csrfToken;
}

const url = new URL(location.href);
if(url.searchParams.get("error") === "1"){
  hint.textContent = "Неверный логин или пароль.";
}

if(url.searchParams.get('forbidden') === '1'){
  hint.textContent = 'Доступ запрещён для вашей роли.';
}

if(url.searchParams.get('error') === 'ratelimit'){
  hint.textContent = 'Слишком много попыток входа. Попробуйте позже.';
}

if(url.searchParams.get('error') === 'csrf'){
  hint.textContent = 'Ошибка проверки безопасности. Обновите страницу и попробуйте снова.';
}
