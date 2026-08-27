import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { HomeRoutingModule } from './home-routing.module';
import { HomeComponent } from './components/home/home.component';

/**
 * [CAIOS] The landing page at `/`.
 *
 * Lazy-loaded, so none of it is downloaded by a user who signs in and goes
 * straight to their deployments. Staged from configs/dashboard/home/ by
 * scripts/build-dashboard.sh; the only upstream edit is the route in
 * patches/ai4-dashboard/0004-home-route.patch.
 */
@NgModule({
    imports: [CommonModule, HomeRoutingModule, HomeComponent],
})
export class HomeModule {}
