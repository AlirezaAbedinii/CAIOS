import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { environment } from '@environments/environment';
import { Observable } from 'rxjs';

/**
 * [CAIOS] An account waiting on, or already given, a decision.
 *
 * `state` is derived by the service from the account's realm roles, never
 * stored: `pending` is the absence of an access:<vo>:<level> role. There is no
 * row anywhere that can disagree with Keycloak.
 */
export interface RegistrationAccount {
    id: string;
    username: string;
    email: string | null;
    first_name: string | null;
    last_name: string | null;
    created: number | null;
    enabled: boolean;
    levels: string[];
    state: 'pending' | 'approved' | 'denied';
}

@Injectable({ providedIn: 'root' })
export class RegistrationService {
    private http = inject(HttpClient);

    /**
     * The approval service sits beside PAPI on the same hostname, at
     * /registration rather than /v1 — same origin, so no second CORS entry and
     * no fifth SAN on the control-plane certificate.
     *
     * Derived from the configured API URL rather than configured separately,
     * because two addresses that must agree are two addresses that can
     * disagree. environment.api.base is `<scheme>://<api host>/v1`.
     */
    private readonly base =
        environment.api.base.replace(/\/v1\/?$/, '') + '/registration';

    accounts(): Observable<RegistrationAccount[]> {
        return this.http.get<RegistrationAccount[]>(`${this.base}/accounts`);
    }

    approve(id: string): Observable<RegistrationAccount> {
        return this.http.post<RegistrationAccount>(
            `${this.base}/approve/${id}`,
            {}
        );
    }

    deny(id: string): Observable<RegistrationAccount> {
        return this.http.post<RegistrationAccount>(
            `${this.base}/deny/${id}`,
            {}
        );
    }
}
