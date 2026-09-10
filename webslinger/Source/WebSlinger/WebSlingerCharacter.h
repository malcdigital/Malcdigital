#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "WebSlingerCharacter.generated.h"

class UCableComponent;
class UCameraComponent;
class UWebShooterComponent;
class UWebSlingerMovementComponent;

/**
 * First-person web-slinger pawn.
 *
 * No mesh by design: in first person the body is never seen, and an unrigged
 * placeholder costs more than it gives. Attach an arms mesh to the camera when
 * you have one - see README, "Adding a body".
 *
 * Most of what makes swinging feel fast in first person is camera work rather
 * than physics. Speed widens the FOV, and the view rolls into the anchor so the
 * horizon banks through an arc. Without those the same motion reads as sliding.
 */
UCLASS()
class WEBSLINGER_API AWebSlingerCharacter : public ACharacter
{
	GENERATED_BODY()

public:
	AWebSlingerCharacter(const FObjectInitializer& ObjectInitializer);

	virtual void Tick(float DeltaTime) override;

	UPROPERTY(EditDefaultsOnly, Category = "Camera") float BaseFOV = 95.f;
	/** Degrees added at MaxSwingSpeed. The whole sense of speed lives here. */
	UPROPERTY(EditDefaultsOnly, Category = "Camera") float SpeedFOVBoost = 22.f;
	UPROPERTY(EditDefaultsOnly, Category = "Camera") float FOVInterpSpeed = 4.f;
	/** Max bank, degrees, at full lean. Above ~20 it starts to make people ill. */
	UPROPERTY(EditDefaultsOnly, Category = "Camera") float MaxSwingRoll = 16.f;
	UPROPERTY(EditDefaultsOnly, Category = "Camera") float RollInterpSpeed = 5.f;
	/** Gamepad look rates, degrees per second. */
	UPROPERTY(EditDefaultsOnly, Category = "Camera") float TurnRateDegrees = 140.f;
	UPROPERTY(EditDefaultsOnly, Category = "Camera") float LookRateDegrees = 110.f;

	/** How far around to look for something to cling to when crawl is held. */
	UPROPERTY(EditDefaultsOnly, Category = "Wall Crawl") float CrawlSearchDistance = 120.f;

	UCameraComponent* GetFirstPersonCamera() const { return Camera; }
	UWebShooterComponent* GetWebShooter() const { return WebShooter; }
	UWebSlingerMovementComponent* GetSlingerMovement() const;

protected:
	virtual void BeginPlay() override;
	virtual void SetupPlayerInputComponent(class UInputComponent* PlayerInputComponent) override;

	void MoveForward(float Value);
	void MoveRight(float Value);
	void Turn(float Value);
	void LookUp(float Value);
	void TurnAtRate(float Value);
	void LookUpAtRate(float Value);
	void Reel(float Value);

	void OnFireWebPressed();
	void OnFireWebReleased();
	void OnZipPressed();
	void OnWallCrawlPressed();
	void OnWallCrawlReleased();

	/** Sweep the surroundings for a clingable face. Camera direction wins ties. */
	bool TryStartWallCrawl();

	void UpdateCameraFeel(float DeltaTime);

private:
	UPROPERTY(VisibleAnywhere, Category = "Camera") TObjectPtr<UCameraComponent> Camera;
	UPROPERTY(VisibleAnywhere, Category = "Web") TObjectPtr<UWebShooterComponent> WebShooter;
	UPROPERTY(VisibleAnywhere, Category = "Web") TObjectPtr<UCableComponent> WebCable;

	bool bWantsToCrawl = false;
	float CurrentRoll = 0.f;
};
