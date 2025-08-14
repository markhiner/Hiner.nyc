document.addEventListener('DOMContentLoaded', () => {
  const whereInput = document.getElementById('where');
  const whenDisplay = document.getElementById('whenDisplay');
  const whenPicker = document.getElementById('whenPicker');
  const nightsInput = document.getElementById('nights');
  const form = document.getElementById('searchForm');

  // Default to tomorrow
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  whenPicker.valueAsDate = tomorrow;

  // Show date picker when clicking display field
  whenDisplay.addEventListener('click', () => {
    if (whenPicker.showPicker) {
      whenPicker.showPicker();
    } else {
      whenPicker.focus();
    }
  });

  // Update display with formatted date
  whenPicker.addEventListener('change', () => {
    whenDisplay.value = formatDisplay(whenPicker.valueAsDate);
  });

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const where = whereInput.value.trim();
    const nights = parseInt(nightsInput.value, 10) || 1;
    const checkIn = whenPicker.value; // YYYY-MM-DD

    const checkOutDate = new Date(whenPicker.value);
    checkOutDate.setDate(checkOutDate.getDate() + nights);
    const checkOut = checkOutDate.toISOString().slice(0, 10);

    fetch('/run_hotels_search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ q: where, check_in_date: checkIn, check_out_date: checkOut })
    }).then(() => {
      window.location.href = 'results.html';
    });
  });

  function formatDisplay(date) {
    return date.toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: '2-digit'
    });
  }
});
