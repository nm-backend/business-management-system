class ConfirmationDialog {
    async confirm(message, title = 'Confirm action') {
        return new Promise((resolve) => {
            const modal = document.createElement('div');
            modal.className = 'modal confirmation-modal';
            modal.innerHTML = `
                <div class="modal-content" role="dialog" aria-modal="true" aria-labelledby="confirmation-title">
                    <div class="modal-header">
                        <h3 id="confirmation-title"></h3>
                        <button class="close" type="button" aria-label="Close">&times;</button>
                    </div>
                    <div class="modal-body"><p class="confirmation-message"></p></div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary confirmation-cancel">Cancel</button>
                        <button type="button" class="btn btn-danger confirmation-submit">Confirm</button>
                    </div>
                </div>`;
            modal.querySelector('#confirmation-title').textContent = title;
            modal.querySelector('.confirmation-message').textContent = message;
            const finish = (result) => {
                modal.remove();
                resolve(result);
            };
            modal.querySelector('.close').addEventListener('click', () => finish(false));
            modal.querySelector('.confirmation-cancel').addEventListener('click', () => finish(false));
            modal.querySelector('.confirmation-submit').addEventListener('click', () => finish(true));
            modal.addEventListener('click', (event) => {
                if (event.target === modal) finish(false);
            });
            document.body.appendChild(modal);
            modal.querySelector('.confirmation-submit').focus();
        });
    }
}

window.confirmation = new ConfirmationDialog();
