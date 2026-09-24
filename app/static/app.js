document.addEventListener('DOMContentLoaded', function () {
    const elements = document.querySelectorAll('[data-bs-dismiss="alert"]');
    elements.forEach(function (element) {
        element.addEventListener('click', function () {
            const alert = element.closest('.alert');
            if (alert) {
                alert.remove();
            }
        });
    });

});
