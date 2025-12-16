const hint = document.getElementById("hint");
const url = new URL(location.href);
if(url.searchParams.get("error") === "1"){
  hint.textContent = "Неверный логин или пароль.";
}

if(url.searchParams.get('forbidden') === '1'){
  hint.textContent = 'Доступ запрещён для вашей роли.';
}
