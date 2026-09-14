#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "InputActionValue.h"
#include "WebSlingerCharacter.generated.h"

class UCableComponent;
class UCameraComponent;
class UInputAction;
class UInputMappingContext;
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
	UPROPERTY(EditDefaultsOnly, Category = "Camera") float MouseSensitivity = 1.f;

	/** How far around to look for something to cling to when crawl is held. */
	UPROPERTY(EditDefaultsOnly, Category = "Wall Crawl") float CrawlSearchDistance = 120.f;

	UCameraComponent* GetFirstPersonCamera() const { return Camera; }
	UWebShooterComponent* GetWebShooter() const { return WebShooter; }
	UWebSlingerMovementComponent* GetSlingerMovement() const;

protected:
	virtual void BeginPlay() override;
	virtual void SetupPlayerInputComponent(class UInputComponent* PlayerInputComponent) override;

	void OnMoveForward(const FInputActionValue& Value);
	void OnMoveRight(const FInputActionValue& Value);
	void OnTurn(const FInputActionValue& Value);
	void OnLookUp(const FInputActionValue& Value);
	void OnTurnRate(const FInputActionValue& Value);
	void OnLookUpRate(const FInputActionValue& Value);
	void OnReel(const FInputActionValue& Value);
	void OnReelReleased();

	void OnFireWebPressed();
	void OnFireWebReleased();
	void OnZipPressed();
	void OnWallCrawlPressed();
	void OnWallCrawlReleased();
	void OnJumpPressed();
	void OnJumpReleased();

	/** Sweep the surroundings for a clingable face. Camera direction wins ties. */
	bool TryStartWallCrawl();

	void UpdateCameraFeel(float DeltaTime);

private:
	UPROPERTY(VisibleAnywhere, Category = "Camera") TObjectPtr<UCameraComponent> Camera;
	UPROPERTY(VisibleAnywhere, Category = "Web") TObjectPtr<UWebShooterComponent> WebShooter;
	UPROPERTY(VisibleAnywhere, Category = "Web") TObjectPtr<UCableComponent> WebCable;

	// Enhanced Input actions and their mapping context are built in C++ rather
	// than authored as .uasset files, so the project stays text-only and builds
	// straight from a clone. See BuildInputAssets().
	UPROPERTY(Transient) TObjectPtr<UInputMappingContext> InputContext;
	UPROPERTY(Transient) TObjectPtr<UInputAction> ActMoveForward;
	UPROPERTY(Transient) TObjectPtr<UInputAction> ActMoveRight;
	UPROPERTY(Transient) TObjectPtr<UInputAction> ActTurn;
	UPROPERTY(Transient) TObjectPtr<UInputAction> ActLookUp;
	UPROPERTY(Transient) TObjectPtr<UInputAction> ActTurnRate;
	UPROPERTY(Transient) TObjectPtr<UInputAction> ActLookUpRate;
	UPROPERTY(Transient) TObjectPtr<UInputAction> ActReel;
	UPROPERTY(Transient) TObjectPtr<UInputAction> ActFireWeb;
	UPROPERTY(Transient) TObjectPtr<UInputAction> ActZip;
	UPROPERTY(Transient) TObjectPtr<UInputAction> ActJump;
	UPROPERTY(Transient) TObjectPtr<UInputAction> ActWallCrawl;

	/** Idempotent; called from both BeginPlay and SetupPlayerInputComponent. */
	void BuildInputAssets();
	void ApplyMappingContext();

	bool bWantsToCrawl = false;
	float CurrentRoll = 0.f;
};
