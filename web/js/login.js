const signUpButton = document.getElementById('signUpButton');
const signInButton = document.getElementById('signInButton');
const signInForm = document.getElementById('signIn');
const signUpForm = document.getElementById('signup');

if (signUpButton && signInButton && signInForm && signUpForm) {
  signUpButton.addEventListener('click', function () {
    signInForm.style.display = 'none';
    signUpForm.style.display = 'block';
    document.getElementById('fName').focus();
  });

  signInButton.addEventListener('click', function () {
    signInForm.style.display = 'block';
    signUpForm.style.display = 'none';
    document.getElementById('email').focus();
  });
}

// Password visibility toggle
document.querySelectorAll('.password-toggle-btn').forEach((btn) => {
  btn.addEventListener('click', function () {
    const wrapper = this.closest('.input-wrapper');
    if (!wrapper) return;
    const input = wrapper.querySelector('input[name="password"]');
    if (!input) return;

    const reveal = input.type === 'password';
    input.type = reveal ? 'text' : 'password';
    this.textContent = reveal ? 'Hide' : 'Show';
    this.setAttribute('aria-pressed', String(reveal));
    this.setAttribute('aria-label', reveal ? 'Hide password' : 'Show password');
  });
});
