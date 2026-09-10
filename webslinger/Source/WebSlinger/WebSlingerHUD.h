#pragma once

#include "CoreMinimal.h"
#include "GameFramework/HUD.h"
#include "WebSlingerHUD.generated.h"

/**
 * Canvas-drawn HUD, so the project needs no UMG assets to be readable.
 *
 * The reticle is the important part. Aim assist is generous, and without a
 * reticle that reacts the player cannot tell a shot that will connect from one
 * that will drop them into the street.
 */
UCLASS()
class WEBSLINGER_API AWebSlingerHUD : public AHUD
{
	GENERATED_BODY()

public:
	UPROPERTY(EditDefaultsOnly, Category = "HUD") FLinearColor IdleColor = FLinearColor(1.f, 1.f, 1.f, 0.35f);
	UPROPERTY(EditDefaultsOnly, Category = "HUD") FLinearColor TargetColor = FLinearColor(1.f, 0.25f, 0.3f, 0.95f);
	UPROPERTY(EditDefaultsOnly, Category = "HUD") FLinearColor AttachedColor = FLinearColor(0.3f, 0.85f, 1.f, 0.95f);
	UPROPERTY(EditDefaultsOnly, Category = "HUD") float ReticleSize = 10.f;
	UPROPERTY(EditDefaultsOnly, Category = "HUD") bool bShowSpeedReadout = true;

	virtual void DrawHUD() override;

private:
	void DrawReticle(float CenterX, float CenterY, const FLinearColor& Color, bool bLocked);
	void DrawSpeedBar(float Speed, float MaxSpeed);
};
