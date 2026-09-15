#pragma once

#include "CoreMinimal.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "Misc/EngineVersionComparison.h"
#include "WebSlingerMovementComponent.generated.h"

/** Custom movement modes. Index 0 is reserved: CustomMovementMode defaults to it. */
UENUM(BlueprintType)
enum EWebSlingerMovementMode : int
{
	CMOVE_None      UMETA(Hidden),
	CMOVE_Swinging  UMETA(DisplayName = "Swinging"),
	CMOVE_WallCrawl UMETA(DisplayName = "Wall Crawl"),
	CMOVE_MAX       UMETA(Hidden),
};

/**
 * Movement for a first-person web-slinger.
 *
 * Swinging is a hard distance constraint, not a spring: the web has a length,
 * the character may move anywhere inside that sphere, and any velocity that
 * would carry it outside is removed at the moment the line goes taut. That is
 * what makes a swing read as a rope rather than a bungee cord.
 *
 * NOT network-predicted. Custom movement modes need FSavedMove_Character work
 * to replicate; this is a single-player prototype. See README.
 */
UCLASS()
class WEBSLINGER_API UWebSlingerMovementComponent : public UCharacterMovementComponent
{
	GENERATED_BODY()

public:
	UWebSlingerMovementComponent();

	// ---------------------------------------------------------------- Swing
	/** Shortest the line may be reeled to. Stops the character slamming into the anchor. */
	UPROPERTY(EditDefaultsOnly, Category = "Swing") float MinRopeLength = 300.f;
	/** Longest line the shooter can hold. */
	UPROPERTY(EditDefaultsOnly, Category = "Swing") float MaxRopeLength = 5000.f;
	/** Manual reel speed, cm/s, on the Reel axis. */
	UPROPERTY(EditDefaultsOnly, Category = "Swing") float ReelSpeed = 1400.f;
	/** Hands-off pumping: shorten near the bottom of the arc, pay out near the top. */
	UPROPERTY(EditDefaultsOnly, Category = "Swing") bool bAutoPump = true;
	UPROPERTY(EditDefaultsOnly, Category = "Swing") float AutoPumpSpeed = 420.f;
	/** How vertical the line must be to count as "the bottom of the arc". */
	UPROPERTY(EditDefaultsOnly, Category = "Swing") float AutoPumpVerticality = 0.82f;
	/** Steering force while swinging, cm/s^2. Applied tangentially only. */
	UPROPERTY(EditDefaultsOnly, Category = "Swing") float SwingThrust = 2400.f;
	/** Fraction of speed bled off per second. Keeps swings from growing forever. */
	UPROPERTY(EditDefaultsOnly, Category = "Swing") float SwingDrag = 0.10f;
	UPROPERTY(EditDefaultsOnly, Category = "Swing") float MaxSwingSpeed = 7000.f;
	/** 0 = dead rope. Raise slightly for a springier, more cartoonish line. */
	UPROPERTY(EditDefaultsOnly, Category = "Swing", meta = (ClampMin = "0.0", ClampMax = "0.9"))
	float TensionRestitution = 0.f;
	/** Upward kick on release, as a fraction of current speed. Makes chaining swings pay. */
	UPROPERTY(EditDefaultsOnly, Category = "Swing") float ReleaseBoost = 0.18f;

	// ----------------------------------------------------------- Wall crawl
	UPROPERTY(EditDefaultsOnly, Category = "Wall Crawl") float MaxCrawlSpeed = 650.f;
	UPROPERTY(EditDefaultsOnly, Category = "Wall Crawl") float CrawlAcceleration = 8.f;
	/** How far past the capsule to look for the surface before letting go. */
	UPROPERTY(EditDefaultsOnly, Category = "Wall Crawl") float CrawlProbeDistance = 45.f;
	/** Gap held between capsule and surface. */
	UPROPERTY(EditDefaultsOnly, Category = "Wall Crawl") float CrawlStickDistance = 12.f;
	/** Surfaces flatter than this (dot with up) are walked, not crawled. */
	UPROPERTY(EditDefaultsOnly, Category = "Wall Crawl") float MaxCrawlableFloorZ = 0.6f;
	/** Push-off when jumping away from a wall. */
	UPROPERTY(EditDefaultsOnly, Category = "Wall Crawl") float WallJumpImpulse = 900.f;

	// -------------------------------------------------------------- Control
	/** Attach the line to a world point. Fails if the point is out of range. */
	bool BeginSwing(const FVector& InAnchor);
	/** Cut the line. bBoost adds the release kick when the character is rising. */
	void EndSwing(bool bBoost);
	bool BeginWallCrawl(const FHitResult& Surface);
	void EndWallCrawl();

	/** -1 pays out, +1 reels in, 0 hands control back to auto-pump. */
	void SetReelInput(float InReel) { ReelInput = FMath::Clamp(InReel, -1.f, 1.f); }

	bool IsSwinging() const   { return MovementMode == MOVE_Custom && CustomMovementMode == CMOVE_Swinging; }
	bool IsWallCrawling() const { return MovementMode == MOVE_Custom && CustomMovementMode == CMOVE_WallCrawl; }

	FVector GetAnchor() const { return Anchor; }
	bool HasWeb() const { return bHasWeb; }
	float GetRopeLength() const { return RopeLength; }
	FVector GetCrawlSurfaceNormal() const { return CrawlSurfaceNormal; }

	/** Signed lean: -1 anchored hard left, +1 anchored hard right. Drives camera roll. */
	float GetSwingLean() const;

	// --------------------------------------------------- UCharacterMovement
	virtual float GetMaxSpeed() const override;
	virtual bool CanAttemptJump() const override;
#if UE_VERSION_OLDER_THAN(5, 4, 0)
	virtual bool DoJump(bool bReplayingMoves) override;
#else
	virtual bool DoJump(bool bReplayingMoves, float DeltaTime) override;
#endif

protected:
	virtual void PhysCustom(float DeltaTime, int32 Iterations) override;
	virtual void OnMovementModeChanged(EMovementMode PreviousMovementMode, uint8 PreviousCustomMode) override;

	void PhysSwinging(float DeltaTime, int32 Iterations);
	void PhysWallCrawl(float DeltaTime, int32 Iterations);

	/** Sphere-sweep from the capsule toward Dir looking for something to cling to. */
	bool TraceCrawlSurface(const FVector& From, const FVector& Dir, FHitResult& Out) const;

private:
	/** World-space point the line is tied to. */
	FVector Anchor = FVector::ZeroVector;
	/** Current constraint radius. */
	float RopeLength = 0.f;
	bool bHasWeb = false;
	float ReelInput = 0.f;
	FVector CrawlSurfaceNormal = FVector::UpVector;
	/** Guards EndSwing/EndWallCrawl against re-entering via OnMovementModeChanged. */
	bool bChangingMode = false;

	void FallOut(float DeltaTime, int32 Iterations);
};
