/**
 * Компонент для управления производством.
 *
 * Отображает список задач и работ, позволяет принимать/отказываться от задач,
 * подтверждать выполненную работу.
 */
class ProductionComponent {
    /**
     * Рендерит страницу производства.
     *
     * @param {HTMLElement} container - Контейнер для рендеринга
     */
    async render(container) {
        container.innerHTML = `
            <header style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                <h1 data-i18n="production.title">Ишлаб чиқариш</h1>
                <div style="display: flex; gap: 10px;">
                    <select id="production-tab" class="form-control" style="width: auto;">
                        <option value="tasks" data-i18n="production.tasks">Вазифалар</option>
                        <option value="works" data-i18n="production.works">Ишлар</option>
                    </select>
                </div>
            </header>
            
            <div id="production-content">
                <!-- Содержимое загружается динамически -->
            </div>
        `;

        await this.loadTasks(container);
        this.setupEventListeners(container);
    }

    /**
     * Загружает список задач.
     *
     * @param {HTMLElement} container - Контейнер
     */
    async loadTasks(container) {
        const contentEl = container.querySelector('#production-content');
        
        try {
            const data = await window.api.request('/api/v1/production/tasks/');
            
            if (data && data.length > 0) {
                contentEl.innerHTML = `
                    <div class="card" style="overflow-x: auto;">
                        <table style="width: 100%; border-collapse: collapse; text-align: left;">
                            <thead>
                                <tr style="border-bottom: 2px solid #eee;">
                                    <th style="padding: 10px;" data-i18n="production.id">ID</th>
                                    <th style="padding: 10px;" data-i18n="production.worker">Ишчи</th>
                                    <th style="padding: 10px;" data-i18n="production.status">Ҳолат</th>
                                    <th style="padding: 10px;" data-i18n="production.assigned_at">Белгиланган</th>
                                    <th style="padding: 10px;" data-i18n="common.actions">Амаллар</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${data.map(t => `
                                    <tr style="border-bottom: 1px solid #eee;">
                                        <td style="padding: 10px;">#${t.id}</td>
                                        <td style="padding: 10px;">${t.worker_name}</td>
                                        <td style="padding: 10px;">
                                            <span class="badge badge-${this.getTaskStatusBadgeClass(t.status)}">
                                                ${this.getTaskStatusDisplay(t.status)}
                                            </span>
                                        </td>
                                        <td style="padding: 10px;">${new Date(t.assigned_at).toLocaleDateString()}</td>
                                        <td style="padding: 10px;">
                                            ${t.status === 'pending' && t.worker_name === window.api.getMe().username ? `
                                                <button class="btn btn-sm btn-success" onclick="window.production.acceptTask(${t.id})">
                                                    <span data-i18n="production.accept">Қабул қилиш</span>
                                                </button>
                                                <button class="btn btn-sm btn-danger" onclick="window.production.refuseTask(${t.id})">
                                                    <span data-i18n="production.refuse">Рад этиш</span>
                                                </button>
                                            ` : '-'}
                                        </td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                `;
            } else {
                contentEl.innerHTML = `<div class="card" style="padding: 20px; text-align: center;" data-i18n="common.no_data">Маълумот йўқ</div>`;
            }
            window.i18n.applyTranslations();
        } catch (e) {
            console.error('Failed to load tasks', e);
            contentEl.innerHTML = `<div class="card" style="padding: 20px; text-align: center; color: red;" data-i18n="common.error">Хатолик</div>`;
            window.i18n.applyTranslations();
        }
    }

    /**
     * Загружает список работ.
     *
     * @param {HTMLElement} container - Контейнер
     */
    async loadWorks(container) {
        const contentEl = container.querySelector('#production-content');
        
        try {
            const data = await window.api.request('/api/v1/production/works/');
            
            if (data && data.length > 0) {
                contentEl.innerHTML = `
                    <div class="card" style="overflow-x: auto;">
                        <table style="width: 100%; border-collapse: collapse; text-align: left;">
                            <thead>
                                <tr style="border-bottom: 2px solid #eee;">
                                    <th style="padding: 10px;" data-i18n="production.id">ID</th>
                                    <th style="padding: 10px;" data-i18n="production.worker">Ишчи</th>
                                    <th style="padding: 10px;" data-i18n="production.product">Маҳсулот</th>
                                    <th style="padding: 10px;" data-i18n="production.quantity">Миқдор</th>
                                    <th style="padding: 10px;" data-i18n="production.status">Ҳолат</th>
                                    <th style="padding: 10px;" data-i18n="common.actions">Амаллар</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${data.map(w => `
                                    <tr style="border-bottom: 1px solid #eee;">
                                        <td style="padding: 10px;">#${w.id}</td>
                                        <td style="padding: 10px;">${w.worker_name}</td>
                                        <td style="padding: 10px;">${w.product_name || '-'}</td>
                                        <td style="padding: 10px;">${w.quantity} ${w.unit}</td>
                                        <td style="padding: 10px;">
                                            <span class="badge badge-${this.getWorkStatusBadgeClass(w.status)}">
                                                ${this.getWorkStatusDisplay(w.status)}
                                            </span>
                                        </td>
                                        <td style="padding: 10px;">
                                            ${w.status === 'awaiting_confirmation' ? `
                                                <button class="btn btn-sm btn-success" onclick="window.production.confirmWork(${w.id})">
                                                    <span data-i18n="production.confirm">Тасдиқлаш</span>
                                                </button>
                                                <button class="btn btn-sm btn-danger" onclick="window.production.rejectWork(${w.id})">
                                                    <span data-i18n="production.reject">Рад этиш</span>
                                                </button>
                                            ` : '-'}
                                        </td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                `;
            } else {
                contentEl.innerHTML = `<div class="card" style="padding: 20px; text-align: center;" data-i18n="common.no_data">Маълумот йўқ</div>`;
            }
            window.i18n.applyTranslations();
        } catch (e) {
            console.error('Failed to load works', e);
            contentEl.innerHTML = `<div class="card" style="padding: 20px; text-align: center; color: red;" data-i18n="common.error">Хатолик</div>`;
            window.i18n.applyTranslations();
        }
    }

    /**
     * Возвращает класс бейджа для статуса задачи.
     *
     * @param {string} status - Статус задачи
     * @returns {string} Класс CSS
     */
    getTaskStatusBadgeClass(status) {
        const classes = {
            'pending': 'warning',
            'accepted': 'success',
            'refused': 'danger',
            'in_progress': 'info',
            'completed': 'primary',
            'confirmed': 'success',
            'rejected': 'danger',
            'cancelled': 'secondary'
        };
        return classes[status] || 'secondary';
    }

    /**
     * Возвращает отображаемое название статуса задачи.
     *
     * @param {string} status - Статус задачи
     * @returns {string} Отображаемое название
     */
    getTaskStatusDisplay(status) {
        const displays = {
            'pending': 'Кутилмоқда',
            'accepted': 'Қабул қилинди',
            'refused': 'Рад этилди',
            'in_progress': 'Жараёнда',
            'completed': 'Бажарилди',
            'confirmed': 'Тасдиқланди',
            'rejected': 'Рад этилди',
            'cancelled': 'Бекор қилинди'
        };
        return displays[status] || status;
    }

    /**
     * Возвращает класс бейджа для статуса работы.
     *
     * @param {string} status - Статус работы
     * @returns {string} Класс CSS
     */
    getWorkStatusBadgeClass(status) {
        const classes = {
            'awaiting_confirmation': 'warning',
            'confirmed': 'success',
            'rejected': 'danger'
        };
        return classes[status] || 'secondary';
    }

    /**
     * Возвращает отображаемое название статуса работы.
     *
     * @param {string} status - Статус работы
     * @returns {string} Отображаемое название
     */
    getWorkStatusDisplay(status) {
        const displays = {
            'awaiting_confirmation': 'Тасдиқлаш кутилмоқда',
            'confirmed': 'Тасдиқланди',
            'rejected': 'Рад этилди'
        };
        return displays[status] || status;
    }

    /**
     * Настраивает обработчики событий.
     *
     * @param {HTMLElement} container - Контейнер
     */
    setupEventListeners(container) {
        const tab = container.querySelector('#production-tab');
        tab.addEventListener('change', (e) => {
            if (e.target.value === 'tasks') {
                this.loadTasks(container);
            } else {
                this.loadWorks(container);
            }
        });

        // Сохраняем ссылку на компонент для глобального доступа
        window.production = this;
        window.production.container = container;
    }

    /**
     * Принимает задачу.
     *
     * @param {number} taskId - ID задачи
     */
    async acceptTask(taskId) {
        try {
            await window.api.request(`/api/v1/production/tasks/${taskId}/accept/`, {
                method: 'POST'
            });
            window.toast.success('Task accepted');
            await this.loadTasks(this.container);
        } catch (error) {
            window.toast.error(error.data?.detail || 'Failed to accept task');
        }
    }

    /**
     * Отказывается от задачи.
     *
     * @param {number} taskId - ID задачи
     */
    async refuseTask(taskId) {
        const reason = prompt('Сабабни киритинг (material_insufficient, no_time, wrong_size, need_helper, equipment_busy, other):');
        if (!reason) return;

        try {
            await window.api.request(`/api/v1/production/tasks/${taskId}/refuse/`, {
                method: 'POST',
                body: JSON.stringify({ reason })
            });
            window.toast.success('Task refused');
            await this.loadTasks(this.container);
        } catch (error) {
            window.toast.error(error.data?.detail || 'Failed to refuse task');
        }
    }

    /**
     * Подтверждает работу.
     *
     * @param {number} workId - ID работы
     */
    async confirmWork(workId) {
        const laborCost = prompt('Иш ҳақини киритинг (фагат эгаси учун):');
        
        try {
            const body = {};
            if (laborCost) body.labor_cost = parseFloat(laborCost);
            
            await window.api.request(`/api/v1/production/works/${workId}/confirm/`, {
                method: 'POST',
                body: JSON.stringify(body)
            });
            window.toast.success('Work confirmed');
            await this.loadWorks(this.container);
        } catch (error) {
            window.toast.error(error.data?.detail || 'Failed to confirm work');
        }
    }

    /**
     * Отклоняет работу.
     *
     * @param {number} workId - ID работы
     */
    async rejectWork(workId) {
        const reason = prompt('Сабабни киритинг:');
        if (!reason) return;

        try {
            await window.api.request(`/api/v1/production/works/${workId}/reject/`, {
                method: 'POST',
                body: JSON.stringify({ reason })
            });
            window.toast.success('Work rejected');
            await this.loadWorks(this.container);
        } catch (error) {
            window.toast.error(error.data?.detail || 'Failed to reject work');
        }
    }
}

window.ProductionComponent = new ProductionComponent();
