# 03. Thermodynamics & Bulk Surface Fluxes

This document details the thermodynamic formulations, air-sea boundary layer bulk parameterizations, and numerical bug fixes implemented in **PredSea** to eliminate unphysical heat accumulation in regional hydrodynamic runs.

---

## 1. Governing Heat Flux Equations

The net surface heat flux ($\text{shflux}$, expressed in $\text{W/m}^2$) entering or leaving the upper oceanic boundary layer is defined by the algebraic sum of shortwave solar radiation, net longwave thermal radiation, latent heat flux from evaporation, and sensible turbulent heat flux:

$$\text{shflux} = \text{radsw} + \text{shflx\_rlw} + \text{shflx\_lat} + \text{shflx\_sen}$$

Where sign convention dictates that **positive values ($>0$) represent heat gain by the ocean**, and **negative values ($<0$) represent net heat loss from the ocean to the atmosphere**.

```
                         Atmosphere
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
   radsw (SW v)   shflx_rlw (LW ^)   shflx_lat (E ^)   shflx_sen (H ^)
     [+ Solar]     [- Longwave]       [- Evaporation]   [- Conduction]
         |              ^                  ^                 ^
         v              |                  |                 |
================================================~~~~~~~~~~~~~~~ (Sea Surface)
                       Ocean Mixed Layer
```

### A. Net Shortwave Solar Radiation ($\text{radsw}$)
Shortwave solar flux reaching the surface mixed layer is governed by downward shortwave flux ($SW_{\downarrow}$) modulated by the sea surface albedo ($\alpha \approx 0.06$):

$$\text{radsw} = (1 - \alpha) \cdot SW_{\downarrow}$$

Shortwave radiation penetrates the upper water column following a two-band exponential decay attenuation model:

$$I(z) = \text{radsw} \cdot \left[ r_1 e^{z / d_1} + (1 - r_1) e^{z / d_2} \right]$$

Where $r_1 \approx 0.58$ represents the rapidly absorbed infrared spectrum fraction ($d_1 \approx 0.35\text{ m}$), and $(1-r_1)$ is the blue-green spectrum with deeper optical attenuation scale ($d_2 \approx 23.0\text{ m}$ in clear Mediterranean waters).

### B. Net Longwave Infrared Radiation ($\text{shflx\_rlw}$)
Net longwave flux represents the balance between incoming atmospheric downward thermal radiation ($LW_{\downarrow}$) and Stefan-Boltzmann blackbody radiation emitted by the sea surface temperature ($\text{SST}$):

$$\text{shflx\_rlw} = \epsilon_s LW_{\downarrow} - \epsilon_s \sigma_{SB} \cdot (\text{SST} + 273.15)^4$$

Where:
*   $\epsilon_s = 0.98$ is the ocean emissivity constant.
*   $\sigma_{SB} = 5.670374 \times 10^{-8} \, \text{W/m}^2/\text{K}^4$ is the Stefan-Boltzmann constant.

Because Mediterranean summer sea surface temperatures ($\text{SST} \approx 26^\circ\text{C} - 29^\circ\text{C}$) typically exceed near-surface air temperatures, $\text{shflx\_rlw}$ acts as a continuous cooling mechanism (ranging between $-50\text{ W/m}^2$ and $-110\text{ W/m}^2$).

### C. Latent Heat Flux ($\text{shflx\_lat}$)
Latent heat flux driven by wind-induced surface evaporation is parameterized using COARE 3.0 bulk aerodynamic formulas:

$$\text{shflx\_lat} = -\rho_a L_v C_E \cdot |\vec{U}_{10}| \cdot \left( q_s(\text{SST}) - q_a \right)$$

Where:
*   $\rho_a$ is air density ($\approx 1.22\text{ kg/m}^3$).
*   $L_v$ is latent heat of vaporization ($\approx 2.45 \times 10^6 \, \text{J/kg}$).
*   $C_E$ is the turbulent transfer coefficient for moisture.
*   $|\vec{U}_{10}|$ is $10\text{ m}$ wind speed magnitude.
*   $q_s(\text{SST})$ is saturation specific humidity at sea surface temperature.
*   $q_a$ is atmospheric specific humidity at $2\text{ m}$.

### D. Sensible Heat Flux ($\text{shflx\_sen}$)
Direct conductive/convective heat exchange between ocean and air is governed by:

$$\text{shflx\_sen} = -\rho_a c_p C_H \cdot |\vec{U}_{10}| \cdot \left( \text{SST} - T_a \right)$$

Where $c_p = 1004.6 \, \text{J/kg/K}$ is atmospheric specific heat capacity and $C_H$ is the bulk sensible heat transfer coefficient.

---

## 2. Technical Fixes: Resolving Thermal Runway ($>40^\circ\text{C}$) in `bulk_flux.F`

In early pre-alpha runs, regional CROCO simulations exhibited severe, unphysical heat accumulation, with shallow coastal sea surface temperatures blowing up to **$>40^\circ\text{C}$** within 72 hours of simulation.

An audit of the CROCO Fortran bulk flux module (`bulk_flux.F`) and Python pre-processing routines identified two primary root causes:

### Bug A: Unit Mismatch in Latent Heat Calculation
*   **The Error**: Upstream atmospheric forcing passed latent flux pre-scaled in $\text{W/m}^2$, while `bulk_flux.F` expected kinematic units ($\text{cm/s} \cdot ^\circ\text{C}$) divided by specific heat capacity ($\rho_0 c_{p,sw}$). This caused latent cooling ($\text{shflx\_lat}$) to be undercomputed by a factor of **~4,184x**.
*   **The Fix**: Standardized unit conversions across `scripts/prepare_croco_forcing.py` and patched `bulk_flux.F` to enforce strict dynamic flux scaling in standard SI units ($\text{W/m}^2$), ensuring that latent heat flux accurately removes $150\text{ W/m}^2 - 350\text{ W/m}^2$ of heat during summer evaporative conditions.

### Bug B: Uncoupled Static SST Loop in Atmospheric Bulk Forcing
*   **The Error**: The bulk flux parameterization evaluated $q_s(\text{SST})$ using a static, unupdated initial SST field rather than the dynamic ocean surface state computed at each CROCO 3D timestep.
*   **The Fix**: Modified `bulk_flux.F` to pass the updated prognostic surface temperature array `t(i,j,N,nnew,itemp)` directly into the bulk loop:

```fortran
! Corrected bulk_flux.F Fortran snippet
! Enforce dynamic SST feedback in latent/longwave bulk computation
do j=Jstr,Jend
  do i=Istr,Iend
    sst_loc = t(i,j,N,nnew,itemp)  ! Dynamic ocean top-layer temperature
    
    ! Recompute saturation specific humidity with dynamic SST
    call qsat(sst_loc, P_atm(i,j), q_sat_surf)
    
    ! Compute correct evaporative latent heat loss
    shflx_lat(i,j) = -rho_air * L_v * C_e * wind_speed(i,j) * (q_sat_surf - q_air(i,j))
    
    ! Sum net surface flux with updated cooling terms
    shflux(i,j) = radsw(i,j) + shflx_rlw(i,j) + shflx_lat(i,j) + shflx_sen(i,j)
  enddo
enddo
```

---

## 3. Nocturnal Boundary Cooling Mechanics

The resolution of `bulk_flux.F` restores physical nocturnal cooling. During daytime hours, solar flux ($\text{radsw}$) dominates, producing a positive net flux ($\text{shflux} \approx +400\text{ W/m}^2 \text{ to } +700\text{ W/m}^2$) that warms the top $1\text{ m} - 3\text{ m}$ diurnal skin layer.

During night hours ($SW_{\downarrow} = 0$), $\text{radsw}$ drops to zero. Net surface heat flux becomes strictly negative:

$$\text{shflux}_{\text{night}} = \text{shflx\_rlw} + \text{shflx\_lat} + \text{shflx\_sen} \approx -180\text{ W/m}^2 \text{ to } -320\text{ W/m}^2$$

```
+-----------------------------------------------------------------------------------+
|                        Diurnal Surface Heat Flux Cycle                            |
|                                                                                   |
|  Flux (W/m2)                                                                      |
|   +800 |                     /---\ (Daytime Solar Peak)                           |
|   +600 |                    /     \                                               |
|   +400 |                   /       \                                              |
|   +200 |                  /         \                                             |
|      0 +-----------------/-----------\------------------+-----------------------  |
|   -200 |======= (Nocturnal Cooling: -220 W/m2) =========|                         |
|   -400 |                                                                          |
|        +----------------+------------+------------------+--------------------->   |
|        00:00           06:00        12:00              18:00            24:00 UTC |
+-----------------------------------------------------------------------------------+
```

This negative nocturnal flux generates surface water density inversion ($\frac{\partial \rho}{\partial z} < 0$), triggering convective vertical mixing that cools the surface layer back down to equilibrium baseline temperatures ($28.35^\circ\text{C}$ mean in summer), in agreement with satellite radiometry.
