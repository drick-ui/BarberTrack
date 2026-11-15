// Client-side validation, delete confirmation, and auto-calculation of the transaction total.
document.addEventListener("DOMContentLoaded", () => {
  // Bootstrap validation
  document.querySelectorAll("form.needs-validation").forEach(form => {
    form.addEventListener("submit", e => {
      const pw = form.querySelector("[name=password], [name=new_password]");
      const cf = form.querySelector("[name=confirm]");
      if (pw && cf) {
        cf.setCustomValidity(pw.value !== cf.value ? "Passwords do not match" : "");
      }
      if (!form.checkValidity()) { e.preventDefault(); e.stopPropagation(); }
      form.classList.add("was-validated");
    });
  });

  // Confirm bago mag-delete
  document.querySelectorAll("form.js-confirm").forEach(form => {
    form.addEventListener("submit", e => {
      if (!confirm(form.dataset.confirm || "Are you sure?")) e.preventDefault();
    });
  });

  // Transaction form total = service price + (product price x quantity).
  // Event delegation: works no matter when the fields are rendered.
  const field = name => document.querySelector(`[name=${name}]`);
  const priceOf = sel => (sel && sel.selectedOptions[0] && parseFloat(sel.selectedOptions[0].dataset.price)) || 0;
  const recalc = () => {
    const service = field("service_id"), product = field("product_id");
    const qty = field("product_qty"), amount = field("amount");
    if (!service || !amount) return;
    const q = qty ? (parseInt(qty.value, 10) || 0) : 0;
    amount.value = (priceOf(service) + priceOf(product) * q).toFixed(2);
  };
  const WATCHED = "[name=service_id], [name=product_id], [name=product_qty]";
  document.addEventListener("change", e => {
    if (!e.target.matches || !e.target.matches(WATCHED)) return;
    if (e.target.name === "product_id") {
      const qty = field("product_qty");
      if (qty) {
        if (!e.target.value) qty.value = "";
        else if (!(parseInt(qty.value, 10) > 0)) qty.value = 1;
      }
    }
    recalc();
  });
  document.addEventListener("input", e => {
    if (e.target.matches && e.target.matches("[name=product_qty]")) recalc();
  });

  // If a service is pre-filled (coming from the Queue page), calculate the total right away
  const amountField = field("amount");
  if (amountField && !amountField.value && field("service_id") && field("service_id").value) recalc();

  // Queue: when a barber is chosen in "Add walk-in" (top), also pre-select that barber in the
  // Waiting rows (bottom) that do not have a barber yet.
  const topBarber = document.querySelector('form[action$="/queue/add"] select[name=barber_id]');
  if (topBarber) {
    const fillWaiting = () => {
      if (!topBarber.value) return;
      document.querySelectorAll('form[action*="/status"] select[name=barber_id]').forEach(sel => {
        if (!sel.value) sel.value = topBarber.value;
      });
    };
    topBarber.addEventListener("change", fillWaiting);
    fillWaiting();
  }

  // Search box above a table: hides the rows that do not match what was typed.
  document.querySelectorAll("[data-table-filter]").forEach(input => {
    const table = document.querySelector(input.dataset.tableFilter);
    if (!table) return;
    input.addEventListener("input", () => {
      const q = input.value.trim().toLowerCase();
      const rows = table.querySelectorAll("tbody tr[data-row]");
      rows.forEach(row => { row.hidden = q !== "" && !row.textContent.toLowerCase().includes(q); });
      const none = table.querySelector("[data-no-results]");
      if (none) none.hidden = q === "" || table.querySelectorAll("tbody tr[data-row]:not([hidden])").length > 0;
    });
  });

  // Show / hide password buttons.
  document.querySelectorAll("[data-toggle-password]").forEach(button => {
    button.addEventListener("click", () => {
      const input = document.querySelector(button.dataset.togglePassword);
      if (!input) return;
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      button.querySelector("i").className = show ? "bi bi-eye-slash" : "bi bi-eye";
    });
  });

  // Success and info messages disappear by themselves.
  document.querySelectorAll(".alert-success, .alert-info").forEach(alert => {
    setTimeout(() => { if (window.bootstrap) bootstrap.Alert.getOrCreateInstance(alert).close(); }, 6000);
  });
});
