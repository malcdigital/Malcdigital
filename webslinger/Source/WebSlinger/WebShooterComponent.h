#pragma once

#include "CoreMinimal.h"
#include "Components/SceneComponent.h"
#include "WebShooterComponent.generated.h"

class UCableComponent;
class UWebSlingerMovementComponent;

/**
 * Finds anchor points and drives the line.
 *
 * Attach this to the camera. In first person the crosshair is the only aim the
 * player has, and a bare centre-ray trace misses constantly at speed - you look
 * where you want to go, not at the one pixel of cornice that would hold. So the
 * search fans out over a cone and scores candidates, preferring points near the
 * centre of aim and close by.
 */
UCLASS(ClassGroup = (WebSlinger), meta = (BlueprintSpawnableComponent))
class WEBSLINGER_API UWebShooterComponent : public USceneComponent
{
	GENERATED_BODY()

public:
	UWebShooterComponent();

	UPROPERTY(EditDefaultsOnly, Category = "Web") float MaxAnchorDistance = 5000.f;
	UPROPERTY(EditDefaultsOnly, Category = "Web") float MinAnchorDistance = 400.f;
	/** An anchor below this height relative to the character drags you into the street. */
	UPROPERTY(EditDefaultsOnly, Category = "Web") float MinAnchorHeight = 250.f;
	/** Fat probe, so thin ledges and railings still register. */
	UPROPERTY(EditDefaultsOnly, Category = "Web") float ProbeRadius = 24.f;

	/** Half-angle of the aim-assist cone, degrees. */
	UPROPERTY(EditDefaultsOnly, Category = "Aim Assist") float AssistConeAngle = 14.f;
	UPROPERTY(EditDefaultsOnly, Category = "Aim Assist") int32 AssistRings = 3;
	UPROPERTY(EditDefaultsOnly, Category = "Aim Assist") int32 AssistSamplesPerRing = 8;
	/** Score cost per degree off-centre. Raise to make assist stingier. */
	UPROPERTY(EditDefaultsOnly, Category = "Aim Assist") float AimPenalty = 120.f;
	/** Score cost per cm of distance. Raise to prefer near anchors. */
	UPROPERTY(EditDefaultsOnly, Category = "Aim Assist") float DistancePenalty = 1.f;

	UPROPERTY(EditDefaultsOnly, Category = "Web") TEnumAsByte<ECollisionChannel> AnchorChannel = ECC_Visibility;
	/** Actors tagged with this are never valid anchors. Tag glass, NPCs, moving props. */
	UPROPERTY(EditDefaultsOnly, Category = "Web") FName NoAnchorTag = TEXT("NoWeb");

	/** Speed of a web-zip pull. */
	UPROPERTY(EditDefaultsOnly, Category = "Zip") float ZipSpeed = 4200.f;
	/** Extra lift on a zip so you clear the ledge instead of hitting its face. */
	UPROPERTY(EditDefaultsOnly, Category = "Zip") float ZipLift = 900.f;

	/** The cable actor-side visual. Set by the owning character. */
	void SetCable(UCableComponent* InCable) { Cable = InCable; }

	/** True when a web fired right now would connect. Drives the reticle. */
	bool HasTargetInSight() const { return bHasTarget; }
	FVector GetCurrentTarget() const { return CurrentTarget; }

	void FireWeb();
	void ReleaseWeb();
	void ZipToTarget();

	/**
	 * Search the aim cone for the best anchor.
	 * @return false if nothing in the cone can hold a line.
	 */
	bool FindAnchor(FVector& OutAnchor) const;

	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

protected:
	virtual void BeginPlay() override;

	bool IsValidAnchor(const FHitResult& Hit) const;
	UWebSlingerMovementComponent* GetSlingerMovement() const;

private:
	UPROPERTY(Transient) TObjectPtr<UCableComponent> Cable;

	bool bHasTarget = false;
	FVector CurrentTarget = FVector::ZeroVector;

	void UpdateCableVisual();
};
